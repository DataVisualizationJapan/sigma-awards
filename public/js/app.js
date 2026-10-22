import { countryJa, langsJa, sizeJa, tagJa } from "./i18n.js";

const PAGE_SIZE = 24;
const IS_DJA = document.body.dataset.catalog === "dja";
const DATA_BASE = document.body.dataset.dataBase || "data/";
// history.replaceState changes the base URL, so resolve relative URLs against the page URL at load time.
const PAGE_URL = location.href;
const DATA_URL = new URL(DATA_BASE, PAGE_URL).href;
const resolveUrl = (path) => new URL(path, PAGE_URL).href;
const entryPath = (id) => `${IS_DJA ? "/dja" : ""}/entries/${encodeURIComponent(id)}/`;
let defaultYear = document.body.dataset.defaultYear || "2026";
const RESULT_VALUES = new Set(["winner", "shortlist", "mention", "entry"]);
const KIND_VALUES = new Set(IS_DJA ? ["project", "portfolio", "individual", "team", "site"] : ["project", "portfolio"]);
const RESULT_LABELS = {
  winner: "受賞",
  shortlist: "ショートリスト",
  mention: "選外表彰",
  entry: "応募",
};
const KIND_LABELS = {
  individual: "個人",
  team: "チーム",
  site: "サイト",
  project: "作品",
  portfolio: "ポートフォリオ",
};

const state = {
  entries: [],
  years: [],
  filtered: [],
  page: 1,
  year: defaultYear,
  category: "",
  coverage: [],
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
  category: document.querySelector("#category"),
  coverage: document.querySelector("#coverage"),
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
  if (state.category) params.set("category", state.category);
  if (state.locale !== "ja") params.set("locale", state.locale);
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

// While the drawer is open the address bar shows the entry page; listUrl keeps the catalog URL to return to.
let listUrl = "";

function writeUrl({ replace = true, measure = true } = {}) {
  let pageLocation = location.href;
  if (state.openId && listUrl) {
    const url = `${listUrl.split("?")[0]}${filtersToSearch()}`;
    if (url === listUrl) return;
    listUrl = url;
    pageLocation = new URL(url, location.origin).href;
  } else {
    const url = nextUrl();
    if (url === currentUrl()) return;
    history[replace ? "replaceState" : "pushState"](null, "", url);
    pageLocation = location.href;
  }
  if (measure && typeof window.gtag === "function") {
    window.gtag("event", "page_view", {
      page_title: document.title,
      page_location: pageLocation,
    });
  }
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  state.query = params.get("q") || "";
  const year = params.get("year");
  if (year === "all") state.year = "";
  else if (year) state.year = year;
  else state.year = defaultYear;
  const result = params.get("result") || "";
  state.result = RESULT_VALUES.has(result) ? result : "";
  const kind = params.get("kind") || "";
  state.kind = KIND_VALUES.has(kind) ? kind : "";
  state.country = params.get("country") || "";
  state.category = IS_DJA ? params.get("category") || "" : "";
  state.locale = params.get("locale") === "src" ? "src" : "ja";
  const page = Number(params.get("page"));
  state.page = Number.isInteger(page) && page >= 1 ? page : 1;
}

function applyUrlToForm() {
  els.q.value = state.query;
  els.result.value = state.result;
  els.kind.value = state.kind;
  if (els.category) els.category.value = state.category;
}

function normalizeYear() {
  if (!state.year) return;
  if (!state.years.includes(Number(state.year))) state.year = defaultYear;
}

function applyFilters() {
  const query = normalize(state.query);
  const tokens = query.split(/\s+/).filter(Boolean);
  state.filtered = state.entries.filter((entry) => {
    if (state.year && String(entry.year) !== state.year) return false;
    const awards = entry.awards || [{ category: "", result: entry.result }];
    if ((state.result || state.category) && !awards.some((award) =>
      (!state.result || award.result === state.result) &&
      (!state.category || award.category === state.category)
    )) return false;
    if (state.kind && entry.kind !== state.kind) return false;
    if (state.country && entry.country !== state.country) return false;
    if (!tokens.length) return true;
    const haystack = normalize(
      [
        entry.title,
        entry.titleJa,
        entry.org,
        ...(entry.awards || []).flatMap((a) => [a.category, categoryJa(a.category)]),
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

function categoryJa(value) {
  if (!IS_DJA) return value;
  const labels = [
    [/Data story or group of stories on a single topic, online or print/i, "単一テーマのデータストーリー（オンライン・紙媒体）"],
    [/Data-driven investigation, which uses data collection and analysis/i, "データ収集・分析による調査報道"],
    [/Journalistic data visualization on a single theme/i, "単一テーマのデータ可視化"],
    [/Data journalism application or website/i, "データジャーナリズムのアプリ・サイト"],
    [/Small newsroom entry \(less than 25 members\)/i, "小規模編集部（25人未満）"],
    [/Small newsrooms \(one or more winners\)/i, "小規模編集部"],
    [/Best Entry from a Small Newsroom/i, "小規模編集部"],
    [/General Excellence(?: Award)? \(Jur(?:y|ors)[’']s? Choice\)/i, "総合優秀賞（審査員選出）"],
    [/Jury[’']s Choice/i, "審査員賞"],
    [/Data[- ]driven investigative journalism/i, "データ調査報道"],
    [/Data[- ]driven investigations?/i, "データ調査報道"],
    [/Data visualisation and storytelling/i, "データ可視化・ストーリーテリング"],
    [/Data[- ]driven applications?/i, "データアプリケーション"],
    [/Data storytelling/i, "データストーリーテリング"],
    [/Data journalism website or section/i, "データジャーナリズムのサイト・部門"],
    [/Data journalism portfolio \(individual\)/i, "個人ポートフォリオ"],
    [/Data journalism portfolio \(team\/newsroom\)/i, "チーム・編集部ポートフォリオ"],
    [/Best (?:data journalism )?team portfolio/i, "チームポートフォリオ"],
    [/Best portfolio [–-] Team/i, "チームポートフォリオ"],
    [/Best data journalism team/i, "データジャーナリズムチーム"],
    [/Best individual portfolio/i, "個人ポートフォリオ"],
    [/Student and young data journalist of the year/i, "学生・若手データジャーナリスト"],
    [/Data visualisation of the year/i, "データ可視化"],
    [/Investigation of the year/i, "調査報道"],
    [/(?:Best )?News data app(?: of the year)?/i, "ニュースデータアプリ"],
    [/Data journalism website of the year/i, "データジャーナリズムサイト"],
    [/Innovation in data journalism/i, "データジャーナリズムの革新"],
    [/Open data(?: award)?/i, "オープンデータ"],
    [/Public[’']?s? choice(?: award)?/i, "読者投票"],
    [/People[’']s Choice Award/i, "読者投票"],
    [/Special Citation|Citation for Excellence/i, "特別表彰"],
  ];
  let translated = value;
  if (/best use of data in a breaking news story/i.test(value)) translated = "速報におけるデータ活用（36時間以内）";
  else for (const [pattern, label] of labels) {
    if (pattern.test(value)) { translated = value.replace(pattern, label); break; }
  }
  return translated.replace(/big media/g, "大規模媒体").replace(/small media/g, "小規模媒体")
    .replace(/Large [Nn]ewsroom|large/g, "大規模編集部")
    .replace(/Small [Nn]ewsroom|small/g, "小規模編集部")
    .replace(/national\/international/g, "国内・国際").replace(/local\/regional/g, "地方・地域");
}

function renderCategories() {
  if (!els.category) return;
  const categories = uniqueSorted((state.year ? state.entries.filter((e) => String(e.year) === state.year) : state.entries).flatMap((entry) => (entry.awards || []).map((a) => a.category)));
  if (!categories.includes(state.category)) state.category = "";
  els.category.innerHTML = '<option value="">すべて</option>' + categories.map((category) =>
    `<option value="${escapeHtml(category)}">${escapeHtml(isJa() ? categoryJa(category) : category)}</option>`
  ).join("");
  els.category.value = state.category;
}

function renderCoverage() {
  if (!els.coverage) return;
  els.coverage.innerHTML = `<summary>収録状況・出典について</summary>
    <p>保存済みの受賞・候補リストから確認できた対象を収録しています。全応募を網羅する一覧ではありません。
    部門別の選考結果と、同一年の同一対象をまとめた件数は異なります。画像・説明が残っていない対象も掲載しています。</p>
    <div class="coverage__scroll"><table><caption>開催年別の収録状況</caption><thead><tr><th>開催年</th><th>対象数</th><th>部門別結果数</th><th>資料の状況</th></tr></thead><tbody>${state.coverage.map((row) =>
      `<tr><th scope="row">${row.year}</th><td>${row.count}</td><td>${row.awardCount}</td><td>${row.notes.map(escapeHtml).join("<br>")}</td></tr>`
    ).join("")}</tbody></table></div>`;
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
        ? `<img class="card__thumb" src="${escapeHtml(resolveUrl(entry.thumb))}" alt="" width="640" height="400" loading="lazy" decoding="async">`
        : "";
      return `
        <article class="card" data-id="${escapeHtml(entry.id)}">
          ${thumb}
          <div class="card__top">
            <span class="badge badge--${escapeHtml(entry.result)}">${escapeHtml(RESULT_LABELS[entry.result] || entry.resultLabel)}</span>
            <span class="card__year">${entry.year}</span>
            <span class="card__kind">${escapeHtml(KIND_LABELS[entry.kind])}</span>
          </div>
          <h2 class="card__title"><a class="card__link" href="${entryPath(entry.id)}">${escapeHtml(displayTitle(entry))}</a></h2>
          ${isJa() && entry.titleJa && entry.titleJa !== entry.title ? `<p class="card__original-title">${escapeHtml(entry.title)}</p>` : ""}
          <p class="card__org">${escapeHtml([entry.org, displayCountry(entry.country)].filter(Boolean).join(" · "))}</p>
          ${langs ? `<p class="card__langs">${escapeHtml(isJa() ? `言語: ${langs}` : `Language: ${entry.langs}`)}</p>` : ""}
          ${langsOriginal && isJa() ? `<p class="card__original">${escapeHtml(entry.langs)}</p>` : ""}
          ${IS_DJA ? `<p class="card__category">${escapeHtml(uniqueSorted((entry.awards || []).map((a) => isJa() ? categoryJa(a.category) : a.category)).join(" · "))}</p>` : ""}
          <p class="card__summary">${escapeHtml(displayCardSummary(entry))}</p>
          <div class="card__tags">${tags}</div>
          <div class="card__actions">
            <a class="card__detail" href="${entryPath(entry.id)}" data-id="${escapeHtml(entry.id)}">詳細</a>
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
  const response = await fetch(`${DATA_URL}details-${year}.json`);
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
  const previousFocus = document.activeElement;
  const hadDrawerFocus = els.drawer.contains(previousFocus);
  const restoreDrawerFocus = () => {
    if (!hadDrawerFocus || previousFocus.isConnected) return;
    const href = previousFocus.getAttribute("href");
    const replacement = href
      ? [...els.drawer.querySelectorAll("a[href]")].find((a) => a.getAttribute("href") === href)
      : previousFocus.tagName === "SUMMARY"
        ? els.drawer.querySelector(".source-records > summary")
        : null;
    (replacement || els.drawerClose).focus();
  };
  const langs = details.langs || entry.langs || "";
  const title = displayTitle(entry);
  if (entry.thumb) {
    els.drawerThumb.hidden = false;
    els.drawerThumb.src = resolveUrl(entry.thumb);
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
    IS_DJA ? renderAwards(entry.awards || []) : "",
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
  if (IS_DJA) {
    els.drawerLinks.innerHTML = renderDjaLinks(entry, details);
    restoreDrawerFocus();
    return;
  }
  const links = details.links?.length ? details.links : entry.url ? [entry.url] : [];
  els.drawerLinks.innerHTML = links
    .map(
      (url, index) =>
        `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${index === 0 ? "作品を開く" : escapeHtml(url)}</a>`
    )
    .join("");
  restoreDrawerFocus();
}

function safeLink(url, label) {
  try {
    if (!["http:", "https:"].includes(new URL(url).protocol)) return "";
  } catch { return ""; }
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
}

function renderAwards(awards) {
  return `<h3>部門・選考結果</h3><ul class="award-list">${awards.map((award) =>
    `<li>${escapeHtml(RESULT_LABELS[award.result])} · ${escapeHtml(isJa() ? categoryJa(award.category) : award.category || "部門記載なし")}
      ${isJa() && categoryJa(award.category) !== award.category ? `<small>${escapeHtml(award.category)}</small>` : ""}</li>`
  ).join("")}</ul>`;
}

function renderDjaLinks(entry, details) {
  const links = details.links || (entry.url ? [entry.url] : []);
  const profiles = details.profileLinks || [];
  const sources = details.sources || entry.sources || [];
  return `<h3>リンク・出典</h3>${links.map((url, i) => safeLink(url, i === 0 ? "作品・受賞対象を開く" : `関連リンク ${i + 1}`)).join("")}
    ${profiles.map((url, i) => safeLink(url, `旧DJA紹介ページ ${i + 1}`)).join("")}
    <p class="source-note">旧サイトや作品のリンクは現在閲覧できない場合があります。以下の保存資料が選考結果の出典です。</p>
    <ul class="source-list">${sources.map((source) => `<li><span>${escapeHtml(source.file)}</span>
      ${source.wayback ? safeLink(source.wayback, "保存ページ（Wayback）") : "<small>個別の保存URLは記録なし</small>"}
      ${source.original ? safeLink(source.original, "出典の元ページ") : ""}</li>`).join("")}</ul>
    ${details.sourceRecords?.length ? `<details class="source-records"><summary>保存資料の記載</summary>${details.sourceRecords.map((record) =>
      `<p><small>${escapeHtml(record.file)}</small><br>${escapeHtml(record.text)}</p>`).join("")}</details>` : ""}`;
}

let returnFocus = null;
let returnSelector = ".card__detail";
// True when the open drawer owns a history entry pushed for it (as opposed to a replaced one).
let drawerPushed = false;

async function openDrawer(id, trigger = null, { mode = "replace" } = {}) {
  const entry = findEntry(id);
  if (!entry) return;
  const wasOpen = !els.drawer.hidden;
  if (!wasOpen) {
    returnFocus = trigger || document.activeElement;
    returnSelector = trigger?.classList.contains("card__link") ? ".card__link" : ".card__detail";
    drawerPushed = mode === "push" || (mode === "keep" && Boolean(history.state?.drawer));
    listUrl = mode === "keep"
      ? `${IS_DJA ? "/dja/" : "/"}${filtersToSearch()}`
      : `${location.pathname}${location.search}`;
  }
  state.openId = id;
  renderDrawer(entry);
  els.drawer.hidden = false;
  els.drawer.dataset.open = "true";
  els.drawerBackdrop.hidden = false;
  document.body.style.overflow = "hidden";
  if (mode === "push" && !wasOpen) history.pushState({ drawer: id }, "", entryPath(id));
  else if (mode === "replace") history.replaceState(null, "", entryPath(id));
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

function closeDrawer({ restoreUrl = true } = {}) {
  const closedId = state.openId;
  state.openId = "";
  els.drawer.hidden = true;
  els.drawer.dataset.open = "false";
  els.drawerBackdrop.hidden = true;
  document.body.style.overflow = "";
  if (returnFocus?.isConnected && returnFocus !== document.body && !els.drawer.contains(returnFocus)) {
    returnFocus.focus();
  } else {
    // The opener is gone, was the page body, or sat inside the drawer: use the same kind of link on the card.
    const card = [...els.grid.querySelectorAll(".card")].find((c) => c.dataset.id === closedId);
    const link = card?.querySelector(returnSelector);
    if (link) link.focus();
    else {
      els.count.tabIndex = -1;
      els.count.focus();
    }
  }
  drawerPushed = false;
  if (restoreUrl && listUrl) history.replaceState(null, "", listUrl);
  listUrl = "";
}

// A drawer opened by a click owns a pushed history entry; closing walks back so Back/Forward stay symmetric.
function requestCloseDrawer() {
  if (state.openId && history.state?.drawer) history.back();
  else closeDrawer();
}

function safeDecode(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}

const ENTRY_PATH_RE = IS_DJA ? /^\/dja\/entries\/([^/]+)\/$/ : /^\/entries\/([^/]+)\/$/;

function syncFromPopState() {
  const match = location.pathname.match(ENTRY_PATH_RE);
  if (match && safeDecode(match[1])) {
    openDrawer(safeDecode(match[1]), null, { mode: "keep" });
    return;
  }
  // Closing with Back lands on the old list entry; apply filters changed while the drawer was open (e.g. locale).
  if (state.openId && drawerPushed && listUrl && listUrl !== `${location.pathname}${location.search}`) {
    history.replaceState(null, "", listUrl);
  }
  restoreFromLocation();
}

function syncFromHash() {
  const match = location.hash.match(/^#e=(.+)$/);
  const id = match ? safeDecode(match[1]) : "";
  if (id) openDrawer(id);
  else if (state.openId) closeDrawer({ restoreUrl: false });
}

function restoreFromLocation() {
  readUrl();
  normalizeYear();
  applyUrlToForm();
  renderYearChips(state.years);
  renderLocaleChips();
  renderCategories();
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
    renderCategories();
    applyFilters();
    renderCards();
    writeUrl({ replace: false });
  });
  els.localeChips.addEventListener("click", (event) => {
    const button = event.target.closest("[data-locale]");
    if (!button) return;
    state.locale = button.dataset.locale;
    renderCategories();
    writeUrl();
    renderLocaleChips();
    renderCategories();
    renderCountries();
    applyFilters();
    renderCards();
    if (state.openId) {
      const entry = findEntry(state.openId);
      const details = state.details.get(entry?.year) || {};
      if (entry) renderDrawer(entry, details[entry.id] || {});
    }
  });
  for (const select of [els.result, els.kind, els.country, els.category].filter(Boolean)) {
    select.addEventListener("change", () => {
      state.result = els.result.value;
      state.kind = els.kind.value;
      state.country = els.country.value;
      state.category = els.category?.value || "";
      state.page = 1;
      applyFilters();
      renderCards();
      writeUrl({ replace: false });
    });
  }
  els.grid.addEventListener("click", (event) => {
    const link = event.target.closest(".card__link, .card__detail");
    if (link) {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const id = link.closest("[data-id]")?.dataset.id;
      // Without loaded data the link navigates to the entry page normally.
      if (!id || !findEntry(id)) return;
      event.preventDefault();
      openDrawer(id, link, { mode: "push" });
      return;
    }
    if (event.target.closest("a")) return;
    const card = event.target.closest("[data-id]");
    if (card) openDrawer(card.dataset.id, null, { mode: "push" });
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
  els.drawerClose.addEventListener("click", requestCloseDrawer);
  els.drawerBackdrop.addEventListener("click", requestCloseDrawer);
  document.addEventListener("keydown", (event) => {
    if (els.drawer.hidden) return;
    if (event.key === "Escape") requestCloseDrawer();
    if (event.key === "Tab") {
      const items = [...els.drawer.querySelectorAll('button, a[href], summary')].filter((el) => el.getClientRects().length);
      const first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  // popstate also fires for hash navigation and handles closing; the URL may already be an entry path here.
  window.addEventListener("hashchange", () => {
    if (location.hash) syncFromHash();
  });
  window.addEventListener("popstate", syncFromPopState);
}

async function init() {
  bind();
  try {
    const response = await fetch(`${DATA_URL}entries.json`);
    if (!response.ok) throw new Error("entries.json");
    const payload = await response.json();
    state.entries = payload.entries.slice().sort(compareEntries);
    state.years = payload.years;
    if (defaultYear === "latest") defaultYear = String(Math.max(...state.years));
    state.coverage = payload.coverage || [];
    renderCoverage();
    readUrl();
    normalizeYear();
    applyUrlToForm();
    renderYearChips(state.years);
    renderLocaleChips();
    renderCategories();
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
