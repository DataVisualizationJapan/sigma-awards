import { countryJa, langsJa, sizeJa, tagJa } from "./i18n.js";

const PAGE_SIZE = 24;
const DEFAULT_YEAR = "2026";
const RESULT_VALUES = new Set(["winner", "shortlist", "mention", "entry"]);
const KIND_VALUES = new Set(["project", "portfolio"]);
const RESULT_LABELS = {
  winner: "受賞",
  shortlist: "ショートリスト",
  mention: "選外表彰",
  entry: "応募",
};
const KIND_LABELS = {
  project: "作品",
  portfolio: "ポートフォリオ",
};

const state = {
  entries: [],
  years: [],
  filtered: [],
  page: 1,
  year: DEFAULT_YEAR,
  result: "",
  kind: "",
  country: "",
  query: "",
  details: new Map(),
  openId: "",
  locale: "ja",
};

const els = {
  q: document.querySelector("#q"),
  yearChips: document.querySelector("#year-chips"),
  localeChips: document.querySelector("#locale-chips"),
  result: document.querySelector("#result"),
  kind: document.querySelector("#kind"),
  country: document.querySelector("#country"),
  count: document.querySelector("#result-count"),
  grid: document.querySelector("#card-grid"),
  empty: document.querySelector("#empty"),
  error: document.querySelector("#error"),
  pager: document.querySelector("#pager"),
  drawer: document.querySelector("#drawer"),
  drawerBackdrop: document.querySelector("#drawer-backdrop"),
  drawerClose: document.querySelector("#drawer-close"),
  drawerThumb: document.querySelector("#drawer-thumb"),
  drawerTitle: document.querySelector("#drawer-title"),
  drawerOriginalTitle: document.querySelector("#drawer-original-title"),
  drawerMeta: document.querySelector("#drawer-meta"),
  drawerOrg: document.querySelector("#drawer-org"),
  drawerLangs: document.querySelector("#drawer-langs"),
  drawerTags: document.querySelector("#drawer-tags"),
  drawerBody: document.querySelector("#drawer-body"),
  drawerSource: document.querySelector("#drawer-source"),
  drawerSourceBody: document.querySelector("#drawer-source-body"),
  drawerLinks: document.querySelector("#drawer-links"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function normalize(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFKC");
}

function isJa() {
  return state.locale === "ja";
}

function displayCountry(value) {
  return isJa() ? countryJa(value) : value;
}

function displayTag(value) {
  return isJa() ? tagJa(value) : value;
}

function displayLangs(value) {
  return isJa() ? langsJa(value) : value;
}

function displaySize(value) {
  return isJa() ? sizeJa(value) : value;
}

function pickJa(translated, original) {
  if (isJa() && translated) return translated;
  return original || "";
}

function displayTitle(entry) {
  return pickJa(entry.titleJa, entry.title);
}

function displayCardSummary(entry) {
  return pickJa(entry.summaryJa, entry.summary);
}

function uniqueSorted(values, labelFn = (value) => value) {
  return [...new Set(values.filter(Boolean))].sort((a, b) =>
    labelFn(a).localeCompare(labelFn(b), isJa() ? "ja" : "en")
  );
}

function compareEntries(a, b) {
  const rank = { winner: 0, shortlist: 1, mention: 2, entry: 3 };
  if (a.year !== b.year) return b.year - a.year;
  if (rank[a.result] !== rank[b.result]) return rank[a.result] - rank[b.result];
  return a.title.localeCompare(b.title, "en");
}

function filtersToSearch() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (!state.year) params.set("year", "all");
  else params.set("year", state.year);
  if (state.result) params.set("result", state.result);
  if (state.kind) params.set("kind", state.kind);
  if (state.country) params.set("country", state.country);
  if (state.page > 1) params.set("page", String(state.page));
  const search = params.toString();
  return search ? `?${search}` : "";
}

function currentUrl() {
  return `${location.pathname}${location.search}${location.hash}`;
}

function nextUrl() {
  return `${location.pathname}${filtersToSearch()}${location.hash}`;
}

function writeUrl({ replace = true, measure = true } = {}) {
  const url = nextUrl();
  if (url === currentUrl()) return;
  history[replace ? "replaceState" : "pushState"](null, "", url);
  if (measure && typeof window.gtag === "function") {
    window.gtag("event", "page_view", {
      page_title: document.title,
      page_location: location.href,
    });
  }
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  state.query = params.get("q") || "";
  const year = params.get("year");
  if (year === "all") state.year = "";
  else if (year) state.year = year;
  else state.year = DEFAULT_YEAR;
  const result = params.get("result") || "";
  state.result = RESULT_VALUES.has(result) ? result : "";
  const kind = params.get("kind") || "";
  state.kind = KIND_VALUES.has(kind) ? kind : "";
  state.country = params.get("country") || "";
  const page = Number(params.get("page"));
  state.page = Number.isInteger(page) && page >= 1 ? page : 1;
}

function applyUrlToForm() {
  els.q.value = state.query;
  els.result.value = state.result;
  els.kind.value = state.kind;
}

function normalizeYear() {
  if (!state.year) return;
  if (!state.years.includes(Number(state.year))) state.year = DEFAULT_YEAR;
}

function applyFilters() {
  const query = normalize(state.query);
  const tokens = query.split(/\s+/).filter(Boolean);
  state.filtered = state.entries.filter((entry) => {
    if (state.year && String(entry.year) !== state.year) return false;
    if (state.result && entry.result !== state.result) return false;
    if (state.kind && entry.kind !== state.kind) return false;
    if (state.country && entry.country !== state.country) return false;
    if (!tokens.length) return true;
    const haystack = normalize(
      [
        entry.title,
        entry.titleJa,
        entry.org,
        entry.country,
        countryJa(entry.country),
        entry.tags.join(" "),
        entry.tags.map(tagJa).join(" "),
        entry.summary,
        entry.summaryJa,
        entry.langs,
        langsJa(entry.langs),
      ].join(" ")
    );
    return tokens.every((token) => haystack.includes(token));
  });
  const maxPage = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
  if (state.page > maxPage) state.page = maxPage;
}

function pageEntries() {
  const start = (state.page - 1) * PAGE_SIZE;
  return state.filtered.slice(start, start + PAGE_SIZE);
}

function renderYearChips(years) {
  const values = ["", ...years.slice().reverse()];
  els.yearChips.innerHTML = values
    .map((year) => {
      const label = year || "すべて";
      const pressed = state.year === String(year);
      return `<button class="chip" type="button" data-year="${escapeHtml(year)}" aria-pressed="${pressed}">${label}</button>`;
    })
    .join("");
}

function renderLocaleChips() {
  [...els.localeChips.querySelectorAll("[data-locale]")].forEach((chip) => {
    chip.setAttribute("aria-pressed", String(chip.dataset.locale === state.locale));
  });
}

function renderCountries() {
  const source = state.year
    ? state.entries.filter((entry) => String(entry.year) === state.year)
    : state.entries;
  const countries = uniqueSorted(
    source.map((entry) => entry.country),
    displayCountry
  );
  const current = countries.includes(state.country) ? state.country : "";
  state.country = current;
  els.country.innerHTML =
    `<option value="">すべて</option>` +
    countries
      .map(
        (country) =>
          `<option value="${escapeHtml(country)}">${escapeHtml(displayCountry(country))}</option>`
      )
      .join("");
  els.country.value = current;
}

function renderCards() {
  const page = pageEntries();
  els.grid.innerHTML = page
    .map((entry) => {
      const tags = entry.tags
        .slice(0, 4)
        .map((tag) => `<span class="tag">${escapeHtml(displayTag(tag))}</span>`)
        .join("");
      const url = entry.url
        ? `<a class="card__open" href="${escapeHtml(entry.url)}" target="_blank" rel="noopener noreferrer">作品を開く</a>`
        : "";
      const langs = displayLangs(entry.langs);
      const langsOriginal = entry.langs && langs !== entry.langs ? entry.langs : "";
      const thumb = entry.thumb
        ? `<img class="card__thumb" src="${escapeHtml(entry.thumb)}" alt="" width="640" height="400" loading="lazy" decoding="async">`
        : "";
      return `
        <article class="card" data-id="${escapeHtml(entry.id)}">
          ${thumb}
          <div class="card__top">
            <span class="badge badge--${escapeHtml(entry.result)}">${escapeHtml(RESULT_LABELS[entry.result] || entry.resultLabel)}</span>
            <span class="card__year">${entry.year}</span>
            <span class="card__kind">${escapeHtml(KIND_LABELS[entry.kind])}</span>
          </div>
          <h2 class="card__title">${escapeHtml(displayTitle(entry))}</h2>
          ${isJa() && entry.titleJa && entry.titleJa !== entry.title ? `<p class="card__original-title">${escapeHtml(entry.title)}</p>` : ""}
          <p class="card__org">${escapeHtml([entry.org, displayCountry(entry.country)].filter(Boolean).join(" · "))}</p>
          ${langs ? `<p class="card__langs">${escapeHtml(isJa() ? `言語: ${langs}` : `Language: ${entry.langs}`)}</p>` : ""}
          ${langsOriginal && isJa() ? `<p class="card__original">${escapeHtml(entry.langs)}</p>` : ""}
          <p class="card__summary">${escapeHtml(displayCardSummary(entry))}</p>
          <div class="card__tags">${tags}</div>
          <div class="card__actions">
            <button class="card__detail" type="button" data-id="${escapeHtml(entry.id)}">詳細</button>
            ${url}
          </div>
        </article>
      `;
    })
    .join("");

  const total = state.filtered.length;
  const from = total === 0 ? 0 : (state.page - 1) * PAGE_SIZE + 1;
  const to = Math.min(state.page * PAGE_SIZE, total);
  const yearNote = state.year ? `${state.year}年` : "全期間";
  els.count.textContent = total
    ? `${yearNote} ${from}–${to}件 / ${total}件`
    : `${yearNote} 0件`;

  els.empty.hidden = total !== 0;
  els.empty.textContent =
    "条件に合う作品がありません。検索語を変えるか、開催年や結果の指定を外してください。";
  renderPager(total);
}

function renderPager(total) {
  const pages = Math.ceil(total / PAGE_SIZE);
  if (pages <= 1) {
    els.pager.hidden = true;
    els.pager.innerHTML = "";
    return;
  }
  els.pager.hidden = false;
  const buttons = [];
  buttons.push(
    `<button type="button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""}>前へ</button>`
  );
  for (let page = 1; page <= pages; page += 1) {
    if (pages > 9 && Math.abs(page - state.page) > 2 && page !== 1 && page !== pages) {
      if (!buttons.at(-1)?.includes("pager__gap")) {
        buttons.push('<span class="pager__gap" aria-hidden="true">…</span>');
      }
      continue;
    }
    const current = page === state.page ? 'aria-current="page"' : "";
    buttons.push(`<button type="button" data-page="${page}" ${current}>${page}</button>`);
  }
  buttons.push(
    `<button type="button" data-page="${state.page + 1}" ${state.page === pages ? "disabled" : ""}>次へ</button>`
  );
  els.pager.innerHTML = buttons.join("");
}

function findEntry(id) {
  return state.entries.find((entry) => entry.id === id);
}

async function loadDetails(year) {
  if (state.details.has(year)) return state.details.get(year);
  const response = await fetch(`data/details-${year}.json`);
  if (!response.ok) throw new Error(`詳細データの読み込みに失敗しました（${year}）`);
  const payload = await response.json();
  state.details.set(year, payload);
  return payload;
}

function section(title, text) {
  if (!text) return "";
  return `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p>`;
}

function renderDrawer(entry, details = {}) {
  const langs = details.langs || entry.langs || "";
  const title = displayTitle(entry);
  if (entry.thumb) {
    els.drawerThumb.hidden = false;
    els.drawerThumb.src = entry.thumb;
    els.drawerThumb.alt = "";
  } else {
    els.drawerThumb.removeAttribute("src");
    els.drawerThumb.hidden = true;
  }
  els.drawerTitle.textContent = title;
  els.drawerOriginalTitle.textContent =
    isJa() && entry.titleJa && entry.titleJa !== entry.title ? entry.title : "";
  els.drawerMeta.textContent = [
    entry.year,
    RESULT_LABELS[entry.result] || entry.resultLabel,
    KIND_LABELS[entry.kind],
    details.date,
    displaySize(details.size),
  ]
    .filter(Boolean)
    .join(" · ");
  els.drawerOrg.textContent = [entry.org, displayCountry(entry.country)].filter(Boolean).join(" · ");
  els.drawerLangs.textContent = langs
    ? isJa()
      ? `言語: ${displayLangs(langs)}`
      : `Language: ${langs}`
    : "";
  els.drawerTags.innerHTML = (entry.tags || [])
    .map((tag) => `<span class="tag">${escapeHtml(displayTag(tag))}</span>`)
    .join("");
  const summary = pickJa(details.summaryJa || entry.summaryJa, details.summary || entry.summary);
  const impact = pickJa(details.impactJa, details.impact);
  const jury = pickJa(details.juryJa, details.jury);
  els.drawerBody.innerHTML = [
    section("概要", summary),
    section("影響", impact),
    section("使った技術", details.tools),
    section("制作", details.authors),
    section("審査コメント", jury),
  ].join("");
  const originalBlocks = [];
  if (isJa() && entry.titleJa && entry.title !== title) originalBlocks.push(section("タイトル", entry.title));
  if (isJa() && (details.summary || entry.summary) && summary !== (details.summary || entry.summary)) {
    originalBlocks.push(section("概要", details.summary || entry.summary));
  }
  if (isJa() && details.impact && impact !== details.impact) originalBlocks.push(section("影響", details.impact));
  if (isJa() && details.jury && jury !== details.jury) originalBlocks.push(section("審査コメント", details.jury));
  if (isJa() && langs && displayLangs(langs) !== langs) originalBlocks.push(section("言語", langs));
  els.drawerSource.hidden = originalBlocks.length === 0;
  els.drawerSourceBody.innerHTML = originalBlocks.join("");
  const links = details.links?.length ? details.links : entry.url ? [entry.url] : [];
  els.drawerLinks.innerHTML = links
    .map(
      (url, index) =>
        `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${index === 0 ? "作品を開く" : escapeHtml(url)}</a>`
    )
    .join("");
}

async function openDrawer(id) {
  const entry = findEntry(id);
  if (!entry) return;
  state.openId = id;
  renderDrawer(entry);
  els.drawer.hidden = false;
  els.drawer.dataset.open = "true";
  els.drawerBackdrop.hidden = false;
  document.body.style.overflow = "hidden";
  history.replaceState(null, "", `${location.pathname}${location.search}#e=${encodeURIComponent(id)}`);
  els.drawerClose.focus();
  try {
    const details = await loadDetails(entry.year);
    if (state.openId === id) renderDrawer(entry, details[id] || {});
  } catch (error) {
    if (state.openId === id) {
      els.drawerBody.insertAdjacentHTML(
        "beforeend",
        section("詳細", "詳細テキストを読み込めませんでした。カードのリンクから作品を開いてください。")
      );
    }
    console.error(error);
  }
}

function closeDrawer() {
  state.openId = "";
  els.drawer.hidden = true;
  els.drawer.dataset.open = "false";
  els.drawerBackdrop.hidden = true;
  document.body.style.overflow = "";
  if (location.hash.startsWith("#e=")) {
    history.replaceState(null, "", location.pathname + location.search);
  }
}

function syncFromHash() {
  const match = location.hash.match(/^#e=(.+)$/);
  if (match) openDrawer(decodeURIComponent(match[1]));
  else if (state.openId) closeDrawer();
}

function restoreFromLocation() {
  readUrl();
  normalizeYear();
  applyUrlToForm();
  renderYearChips(state.years);
  renderCountries();
  applyFilters();
  renderCards();
  syncFromHash();
}

function bind() {
  let timer = 0;
  document.querySelector("#filters").addEventListener("submit", (event) => {
    event.preventDefault();
  });
  els.q.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      state.query = els.q.value;
      state.page = 1;
      applyFilters();
      renderCards();
      writeUrl({ replace: true });
    }, 150);
  });
  els.yearChips.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.year = button.dataset.year;
    state.page = 1;
    [...els.yearChips.querySelectorAll(".chip")].forEach((chip) => {
      chip.setAttribute("aria-pressed", String(chip === button));
    });
    renderCountries();
    applyFilters();
    renderCards();
    writeUrl({ replace: false });
  });
  els.localeChips.addEventListener("click", (event) => {
    const button = event.target.closest("[data-locale]");
    if (!button) return;
    state.locale = button.dataset.locale;
    renderLocaleChips();
    renderCountries();
    applyFilters();
    renderCards();
    if (state.openId) {
      const entry = findEntry(state.openId);
      const details = state.details.get(entry?.year) || {};
      if (entry) renderDrawer(entry, details[entry.id] || {});
    }
  });
  for (const select of [els.result, els.kind, els.country]) {
    select.addEventListener("change", () => {
      state.result = els.result.value;
      state.kind = els.kind.value;
      state.country = els.country.value;
      state.page = 1;
      applyFilters();
      renderCards();
      writeUrl({ replace: false });
    });
  }
  els.grid.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    const card = event.target.closest("[data-id]");
    if (card) openDrawer(card.dataset.id);
  });
  els.pager.addEventListener("click", (event) => {
    const button = event.target.closest("[data-page]");
    if (!button || button.disabled) return;
    const page = Number(button.dataset.page);
    const maxPage = Math.ceil(state.filtered.length / PAGE_SIZE);
    if (!page || page < 1 || page > maxPage) return;
    state.page = page;
    renderCards();
    writeUrl({ replace: false });
    els.count.scrollIntoView({ block: "start" });
  });
  els.drawerClose.addEventListener("click", closeDrawer);
  els.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.drawer.hidden) closeDrawer();
  });
  window.addEventListener("hashchange", syncFromHash);
  window.addEventListener("popstate", restoreFromLocation);
}

async function init() {
  bind();
  try {
    const response = await fetch("data/entries.json");
    if (!response.ok) throw new Error("entries.json");
    const payload = await response.json();
    state.entries = payload.entries.slice().sort(compareEntries);
    state.years = payload.years;
    readUrl();
    normalizeYear();
    applyUrlToForm();
    renderYearChips(state.years);
    renderLocaleChips();
    renderCountries();
    applyFilters();
    renderCards();
    writeUrl({ replace: true, measure: false });
    syncFromHash();
  } catch (error) {
    els.error.hidden = false;
    els.error.textContent =
      "作品データを読み込めませんでした。ページを再読み込みするか、ローカルサーバー経由で開いているか確認してください。";
    console.error(error);
  }
}

init();
