#!/usr/bin/env python3
"""Build crawlable static HTML from the committed catalog JSON.

Copies ``public/`` to ``dist/`` and adds, without touching ``public/``:
  * one page per entry   (/entries/{id}/, /dja/entries/{id}/)
  * one page per year    (/{year}/, /dja/{year}/)
  * the first 24 cards embedded in /index.html and /dja/index.html
  * /sitemap.xml
Standard library only. Output is deterministic (no timestamps, fixed order).
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

SITE = "https://sigma-awards.data-visualization.jp"
PAGE_SIZE = 24
MARKER = ".build-pages"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

RESULT_LABELS = {"winner": "受賞", "shortlist": "ショートリスト", "mention": "選外表彰", "entry": "応募"}
RESULT_EN = {"winner": "Winner", "shortlist": "Shortlist", "mention": "Special Mention", "entry": "Entry"}
RESULT_RANK = {"winner": 0, "shortlist": 1, "mention": 2, "entry": 3}
KIND_LABELS = {"individual": "個人", "team": "チーム", "site": "サイト", "project": "作品", "portfolio": "ポートフォリオ"}

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
    '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
    '    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+JP:wght@400;500;600&amp;'
    'family=Noto+Sans+JP:wght@400;500;600&amp;display=swap" rel="stylesheet" />\n'
    "    <link rel=\"icon\" href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect fill='%230F6CBD' width='32' height='32' rx='6'/%3E%3Ctext x='16' y='22' text-anchor='middle' "
    "font-size='18' fill='white' font-family='Georgia, serif'%3E\u03a3%3C/text%3E%3C/svg%3E\" />"
)

CATALOGS = {
    "sigma": {
        "name": "Sigma Awards",
        "prefix": "",          # URL prefix of the catalog root
        "data": "data",
        "index": "index.html",
    },
    "dja": {
        "name": "Data Journalism Awards",
        "prefix": "/dja",
        "data": "data/dja",
        "index": "dja/index.html",
    },
}


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


# ---------------------------------------------------------------- i18n (port of public/js/i18n.js)

def load_i18n(path):
    tables = {"SIZE_JA": {}, "TAG_JA": {}, "COUNTRY_JA": {}}
    lang = []
    if not path.exists():
        return tables, lang
    text = path.read_text(encoding="utf-8")
    for name in tables:
        m = re.search(r"export const %s = \{(.*?)\n\};" % name, text, re.S)
        if not m:
            continue
        for k in re.finditer(r'^\s*(?:"((?:[^"\\]|\\.)*)"|([A-Za-z_]\w*)):\s*"((?:[^"\\]|\\.)*)",?\s*$', m.group(1), re.M):
            tables[name][json.loads('"%s"' % k.group(1)) if k.group(1) is not None else k.group(2)] = json.loads('"%s"' % k.group(3))
    m = re.search(r"const LANG_JA = \[(.*?)\n\];", text, re.S)
    if m:
        for k in re.finditer(r'\[\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\]', m.group(1)):
            lang.append((json.loads('"%s"' % k.group(1)), json.loads('"%s"' % k.group(2))))
    return tables, lang


CATEGORY_LABELS = [
    (r"Data story or group of stories on a single topic, online or print", "単一テーマのデータストーリー（オンライン・紙媒体）"),
    (r"Data-driven investigation, which uses data collection and analysis", "データ収集・分析による調査報道"),
    (r"Journalistic data visualization on a single theme", "単一テーマのデータ可視化"),
    (r"Data journalism application or website", "データジャーナリズムのアプリ・サイト"),
    (r"Small newsroom entry \(less than 25 members\)", "小規模編集部（25人未満）"),
    (r"Small newsrooms \(one or more winners\)", "小規模編集部"),
    (r"Best Entry from a Small Newsroom", "小規模編集部"),
    (r"General Excellence(?: Award)? \(Jur(?:y|ors)[’']s? Choice\)", "総合優秀賞（審査員選出）"),
    (r"Jury[’']s Choice", "審査員賞"),
    (r"Data[- ]driven investigative journalism", "データ調査報道"),
    (r"Data[- ]driven investigations?", "データ調査報道"),
    (r"Data visualisation and storytelling", "データ可視化・ストーリーテリング"),
    (r"Data[- ]driven applications?", "データアプリケーション"),
    (r"Data storytelling", "データストーリーテリング"),
    (r"Data journalism website or section", "データジャーナリズムのサイト・部門"),
    (r"Data journalism portfolio \(individual\)", "個人ポートフォリオ"),
    (r"Data journalism portfolio \(team/newsroom\)", "チーム・編集部ポートフォリオ"),
    (r"Best (?:data journalism )?team portfolio", "チームポートフォリオ"),
    (r"Best portfolio [–-] Team", "チームポートフォリオ"),
    (r"Best data journalism team", "データジャーナリズムチーム"),
    (r"Best individual portfolio", "個人ポートフォリオ"),
    (r"Student and young data journalist of the year", "学生・若手データジャーナリスト"),
    (r"Data visualisation of the year", "データ可視化"),
    (r"Investigation of the year", "調査報道"),
    (r"(?:Best )?News data app(?: of the year)?", "ニュースデータアプリ"),
    (r"Data journalism website of the year", "データジャーナリズムサイト"),
    (r"Innovation in data journalism", "データジャーナリズムの革新"),
    (r"Open data(?: award)?", "オープンデータ"),
    (r"Public[’']?s? choice(?: award)?", "読者投票"),
    (r"People[’']s Choice Award", "読者投票"),
    (r"Special Citation|Citation for Excellence", "特別表彰"),
]
CATEGORY_PATTERNS = [(re.compile(p, re.I), label) for p, label in CATEGORY_LABELS]


def category_ja(value):
    """Port of categoryJa() in app.js (DJA only)."""
    value = value or ""
    translated = value
    if re.search(r"best use of data in a breaking news story", value, re.I):
        translated = "速報におけるデータ活用（36時間以内）"
    else:
        for pattern, label in CATEGORY_PATTERNS:
            if pattern.search(value):
                translated = pattern.sub(lambda _m: label, value, count=1)
                break
    translated = translated.replace("big media", "大規模媒体").replace("small media", "小規模媒体")
    translated = re.sub(
        r"\b(?:small|large) newsroom\b|\b(?:small|large)\b",
        lambda m: "小規模編集部" if m.group(0).lower().startswith("small") else "大規模編集部",
        translated, flags=re.I | re.ASCII)
    return translated.replace("national/international", "国内・国際").replace("local/regional", "地方・地域")


class I18n:
    def __init__(self, path):
        self.tables, self.lang = load_i18n(path)
        self._lang_re = []
        for source, target in self.lang:
            try:
                self._lang_re.append((re.compile(source, re.I), target))
            except re.error:
                self._lang_re.append((re.compile(re.escape(source), re.I), target))

    def country(self, v):
        return self.tables["COUNTRY_JA"].get(v, v)

    def tag(self, v):
        return self.tables["TAG_JA"].get(v, v)

    def size(self, v):
        return self.tables["SIZE_JA"].get(v, v)

    def langs(self, v):
        if not v:
            return ""
        text = str(v)
        for rx, target in self._lang_re:
            text = rx.sub(lambda _m, t=target: t, text)
        return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- helpers

def sort_key(entry):
    return (-entry["year"], RESULT_RANK.get(entry["result"], 9), entry["title"].casefold(), entry["id"])


def http_url(url):
    try:
        p = urlparse(url or "")
    except ValueError:
        return ""
    return url if p.scheme in ("http", "https") and p.netloc and not re.search(r"\s", url) else ""


def safe_link(url, label):
    url = http_url(url)
    if not url:
        return ""
    return '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (esc(url), esc(label))


def abs_thumb(thumb, catalog_prefix):
    """Resolve a thumb relative to the catalog's list page, as the browser would."""
    if not thumb:
        return ""
    base = (catalog_prefix or "") + "/"
    return urljoin(base, thumb)


def plain(text):
    """Text without HTML tags/comments, for <title>, meta and JSON-LD."""
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"</?[A-Za-z][^>]*>", " ", text)).strip()


def truncate(text, limit=120):
    text = plain(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def json_ld(data):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return (text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def entry_path(cat, entry_id):
    return "%s/entries/%s/" % (CATALOGS[cat]["prefix"], quote(entry_id, safe=""))


def year_path(cat, year):
    return "%s/%s/" % (CATALOGS[cat]["prefix"], year)


def list_path(cat, year):
    return "%s/?year=%s" % (CATALOGS[cat]["prefix"], year)


# ---------------------------------------------------------------- shared page parts

class Shell:
    """Head/footer pieces taken from the existing list pages so they stay in sync."""

    def __init__(self, public):
        idx = (public / "index.html").read_text(encoding="utf-8")
        m = re.search(r"<!-- Google tag \(gtag\.js\) -->.*?gtag\('config'[^)]*\);\s*</script>", idx, re.S)
        self.gtag = m.group(0) if m else ""
        self.footer = {}
        for cat, conf in CATALOGS.items():
            src = (public / conf["index"]).read_text(encoding="utf-8")
            m = re.search(r'<footer class="site-footer">.*?</footer>', src, re.S)
            self.footer[cat] = m.group(0) if m else '<footer class="site-footer"></footer>'

    def page(self, cat, *, title, description, canonical, body, og_type="website", og_image="", ld=None):
        og = [
            ("og:title", title), ("og:description", description), ("og:url", canonical), ("og:type", og_type),
            ("og:site_name", CATALOGS[cat]["name"]),
        ]
        if og_image:
            og.append(("og:image", og_image))
        og_html = "\n    ".join('<meta property="%s" content="%s" />' % (k, esc(v)) for k, v in og)
        ld_html = ""
        if ld:
            ld_html = '\n    <script type="application/ld+json">\n%s\n    </script>' % json_ld(ld)
        return """<!DOCTYPE html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    %s
    <title>%s</title>
    <meta name="description" content="%s" />
    <link rel="canonical" href="%s" />
    %s
    %s
    <link rel="stylesheet" href="/css/styles.css" />%s
  </head>
  <body class="static-page">
%s
    %s
  </body>
</html>
""" % (self.gtag, esc(title), esc(description), esc(canonical), og_html, FONTS, ld_html, body, self.footer[cat])


def masthead(cat):
    return """    <header class="masthead">
      <div class="masthead__inner">
        <p class="masthead__kicker">Data Visualization Japan</p>
        <nav class="award-nav" aria-label="アワード"><a href="/"%s>Sigma Awards</a><a href="/dja/"%s>Data Journalism Awards</a></nav>
      </div>
    </header>""" % ("" if cat != "sigma" else ' aria-current="page"', "" if cat != "dja" else ' aria-current="page"')


def year_nav(cat, years, current=None):
    links = []
    for y in years:
        if y == current:
            links.append('<li><a href="%s" aria-current="page">%s</a></li>' % (year_path(cat, y), y))
        else:
            links.append('<li><a href="%s">%s</a></li>' % (year_path(cat, y), y))
    return '<nav class="year-index" aria-label="年別一覧"><h2>年別一覧</h2><ul>%s</ul></nav>' % "".join(links)


# ---------------------------------------------------------------- entry rendering

def para_section(title, text):
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"\n{2,}", str(text)) if part.strip()]
    return "<h2>%s</h2>%s" % (esc(title), "".join("<p>%s</p>" % esc(part) for part in parts))


def pick_ja(translated, original):
    return translated or original or ""


def render_awards(awards, i18n):
    items = []
    for a in awards:
        cat_ja = category_ja(a.get("category", ""))
        label = cat_ja if a.get("category") else "部門記載なし"
        small = "<small>%s</small>" % esc(a["category"]) if a.get("category") and cat_ja != a["category"] else ""
        items.append("<li>%s · %s\n      %s</li>" % (esc(RESULT_LABELS.get(a.get("result"), a.get("result"))), esc(label), small))
    return '<h2>部門・選考結果</h2><ul class="award-list">%s</ul>' % "".join(items)


def render_refs(refs):
    items = [r for r in refs or [] if isinstance(r, dict) and http_url(r.get("url"))]
    if not items:
        return ""
    lis = "".join('<li><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></li>' % (
        esc(r["url"]), esc(r.get("label") or r["url"])) for r in items)
    return '<h2 class="ref-title">本文中のリンク</h2><ul class="ref-list">%s</ul>' % lis


def render_dja_links(entry, details):
    links = details.get("links") or ([entry["url"]] if entry.get("url") else [])
    profiles = details.get("profileLinks") or []
    sources = details.get("sources") or entry.get("sources") or []
    parts = ["<h2>リンク・出典</h2>"]
    parts += [safe_link(u, "作品・受賞対象を開く" if i == 0 else "関連リンク %d" % (i + 1)) for i, u in enumerate(links)]
    parts += [safe_link(u, "旧DJA紹介ページ %d" % (i + 1)) for i, u in enumerate(profiles)]
    parts.append('<p class="source-note">旧サイトや作品のリンクは現在閲覧できない場合があります。以下の保存資料が選考結果の出典です。</p>')
    lis = []
    for s in sources:
        wb = safe_link(s.get("wayback"), "保存ページ（Wayback）") if s.get("wayback") else "<small>個別の保存URLは記録なし</small>"
        orig = safe_link(s.get("original"), "出典の元ページ") if s.get("original") else ""
        lis.append("<li><span>%s</span>\n      %s\n      %s</li>" % (esc(s.get("file")), wb, orig))
    parts.append('<ul class="source-list">%s</ul>' % "".join(lis))
    if details.get("sourceRecords"):
        recs = "".join("<p><small>%s</small><br>%s</p>" % (esc(r.get("file")), esc(r.get("text"))) for r in details["sourceRecords"])
        parts.append('<details class="source-records"><summary>保存資料の記載</summary>%s</details>' % recs)
    return "".join(parts)


def render_entry_page(shell, i18n, cat, entry, details, years):
    conf = CATALOGS[cat]
    is_dja = cat == "dja"
    details = details or {}
    year = entry["year"]
    title_ja = entry.get("titleJa")
    title = title_ja or entry["title"]
    langs = details.get("langs") or entry.get("langs") or ""
    result_label = RESULT_LABELS.get(entry["result"]) or entry.get("resultLabel") or ""
    summary_src = details.get("summary") or entry.get("summary") or ""
    summary = pick_ja(details.get("summaryJa") if details.get("summary") else entry.get("summaryJa"), summary_src)
    impact_src, jury_src = details.get("impact") or "", details.get("jury") or ""
    impact = pick_ja(details.get("impactJa"), impact_src)
    jury = pick_ja(details.get("juryJa"), jury_src)

    meta = " · ".join(str(x) for x in [year, result_label, KIND_LABELS.get(entry.get("kind")),
                                       details.get("date"), i18n.size(details.get("size")) if details.get("size") else None] if x)
    org_line = " · ".join(x for x in [entry.get("org"), i18n.country(entry.get("country"))] if x)
    tags = "".join('<span class="tag">%s</span>' % esc(i18n.tag(t)) for t in entry.get("tags") or [])
    thumb = abs_thumb(entry.get("thumb"), conf["prefix"])

    body_parts = [
        render_awards(entry.get("awards") or [], i18n) if is_dja else "",
        para_section("概要", summary), para_section("影響", impact),
        para_section("使った技術", details.get("tools")), para_section("制作", details.get("authors")),
        para_section("審査コメント", jury),
    ]
    orig = []
    if title_ja and entry["title"] != title:
        orig.append(para_section("タイトル", entry["title"]))
    if summary_src and summary != summary_src:
        orig.append(para_section("概要", summary_src))
    if impact_src and impact != impact_src:
        orig.append(para_section("影響", impact_src))
    if jury_src and jury != jury_src:
        orig.append(para_section("審査コメント", jury_src))
    if langs and i18n.langs(langs) != langs:
        orig.append(para_section("言語", langs))
    orig_html = '<section class="detail__source"><h2 class="detail__source-title">原文</h2>%s</section>' % "".join(orig) if orig else ""

    if is_dja:
        links_html = render_dja_links(entry, details)
    else:
        urls = [u for u in (details.get("links") or ([entry["url"]] if entry.get("url") else [])) if http_url(u)]
        notes = details.get("linkNotes") if isinstance(details.get("linkNotes"), dict) else {}
        links_html = "".join(
            '<span class="link-row"><a href="%s" target="_blank" rel="noopener noreferrer">%s</a>%s</span>' % (
                esc(u), "作品を開く" if i == 0 else esc(u),
                ('<small class="link-note">%s</small>' % esc(notes[u])) if isinstance(notes.get(u), str) and notes[u] else "")
            for i, u in enumerate(urls))
        links_html += render_refs(details.get("refs"))

    lang_line = ("言語: %s" % i18n.langs(langs)) if langs else ""
    page_title = "%s | %s %s" % (plain(title) or title, conf["name"], year)
    desc = truncate(summary or summary_src)
    if not desc:
        desc = "%s %s年の%s: %s%s。" % (conf["name"], year, KIND_LABELS.get(entry.get("kind"), "作品"), plain(title),
                                      "（%s）" % org_line if org_line else "")
    canonical = SITE + entry_path(cat, entry["id"])
    og_image = SITE + thumb if thumb else ""

    if is_dja:
        awards = ["%s %s %s%s" % (conf["name"], year, RESULT_EN.get(a.get("result"), a.get("result")),
                                  ": " + a["category"] if a.get("category") else "") for a in entry.get("awards") or []]
        award = awards or "%s %s %s" % (conf["name"], year, RESULT_EN.get(entry["result"], entry["result"]))
    else:
        award = "%s %s %s" % (conf["name"], year, RESULT_EN.get(entry["result"], entry["result"]))
    ld = {"@context": "https://schema.org", "@type": "CreativeWork", "name": plain(entry["title"]) or entry["title"]}
    if title_ja and title_ja != entry["title"]:
        ld["alternateName"] = plain(title_ja)
    if entry.get("org"):
        ld["author"] = {"@type": "Organization", "name": plain(entry["org"])}
    work_url = http_url(entry.get("url"))
    if work_url:
        ld["url"] = work_url
    ld["description"] = desc
    if entry.get("tags"):
        ld["keywords"] = ", ".join(entry["tags"])
    ld["award"] = award
    if og_image:
        ld["image"] = og_image
    ld["mainEntityOfPage"] = canonical

    thumb_html = '<img class="detail__thumb" src="%s" alt="" width="640" height="400" decoding="async">' % esc(thumb) if thumb else ""
    original_title = ('<p class="detail__original-title">%s</p>' % esc(entry["title"])) if title_ja and title_ja != entry["title"] else ""
    body = """%s
    <main class="page detail">
      <nav class="crumbs" aria-label="関連ページ">
        <a href="%s">← %s年の一覧に戻る</a>
        <a href="%s">%s年 作品リスト</a>
      </nav>
      <article class="detail__article">
        %s
        <p class="detail__meta">%s</p>
        <h1>%s</h1>
        %s
        %s
        %s
        %s
        %s
        %s
        %s
      </article>
      %s
    </main>""" % (
        masthead(cat), esc(list_path(cat, year)), year, esc(year_path(cat, year)), year, thumb_html, esc(meta), esc(title),
        original_title, ('<p class="detail__org">%s</p>' % esc(org_line)) if org_line else "",
        ('<p class="detail__langs">%s</p>' % esc(lang_line)) if lang_line else "",
        ('<div class="detail__tags">%s</div>' % tags) if tags else "",
        ('<div class="detail__body">\n          %s\n        </div>' % "\n          ".join(p for p in body_parts if p)) if any(body_parts) else "",
        orig_html, ('<div class="detail__links">%s</div>' % links_html) if links_html else "", year_nav(cat, years, year))
    return shell.page(cat, title=page_title, description=desc, canonical=canonical, body=body,
                      og_type="article", og_image=og_image, ld=ld)


# ---------------------------------------------------------------- year page / cards

def render_year_page(shell, i18n, cat, year, entries, years):
    conf = CATALOGS[cat]
    counts = {}
    for e in entries:
        counts[e["result"]] = counts.get(e["result"], 0) + 1
    breakdown = "、".join("%s%d件" % (RESULT_LABELS[r], counts[r]) for r in RESULT_RANK if r in counts)
    title = "%s %s年 エントリー一覧（%d件）" % (conf["name"], year, len(entries))
    desc = "%s %s年に掲載された%d作品の一覧（%s）。作品名、媒体、国、結果と各作品のページへのリンクを掲載しています。" % (
        conf["name"], year, len(entries), breakdown)
    items = []
    for e in entries:
        meta = " · ".join(x for x in [e.get("org"), i18n.country(e.get("country")), RESULT_LABELS.get(e["result"]) or e.get("resultLabel")] if x)
        sub = ""
        if e.get("titleJa") and e["titleJa"] != e["title"]:
            sub = '<span class="entry-list__original">%s</span>' % esc(e["title"])
        items.append('<li><a href="%s">%s</a>%s<span class="entry-list__meta">%s</span></li>' % (
            esc(entry_path(cat, e["id"])), esc(e.get("titleJa") or e["title"]), sub, esc(meta)))
    body = """%s
    <main class="page detail">
      <nav class="crumbs" aria-label="関連ページ">
        <a href="%s">← %s年を検索・絞り込みで見る</a>
      </nav>
      <h1>%s</h1>
      <p class="detail__org">%s</p>
      <ol class="entry-list">
        %s
      </ol>
      %s
    </main>""" % (masthead(cat), esc(list_path(cat, year)), year, esc(title), esc(desc), "\n        ".join(items),
                  year_nav(cat, years, year))
    return shell.page(cat, title="%s | %s" % (title, conf["name"]), description=desc,
                      canonical=SITE + year_path(cat, year), body=body)


def render_card(i18n, cat, e):
    conf = CATALOGS[cat]
    href = entry_path(cat, e["id"])
    tags = "".join('<span class="tag">%s</span>' % esc(i18n.tag(t)) for t in (e.get("tags") or [])[:4])
    url = http_url(e.get("url"))
    open_link = ('<a class="card__open" href="%s" target="_blank" rel="noopener noreferrer">作品を開く</a>' % esc(url)) if url else ""
    langs = i18n.langs(e.get("langs"))
    langs_original = e["langs"] if e.get("langs") and langs != e["langs"] else ""
    thumb = abs_thumb(e.get("thumb"), conf["prefix"])
    thumb_html = ('<img class="card__thumb" src="%s" alt="" width="640" height="400" loading="lazy" decoding="async">' % esc(thumb)) if thumb else ""
    title = e.get("titleJa") or e["title"]
    parts = [thumb_html,
             '<div class="card__top"><span class="badge badge--%s">%s</span><span class="card__year">%s</span><span class="card__kind">%s</span></div>' % (
                 esc(e["result"]), esc(RESULT_LABELS.get(e["result"]) or e.get("resultLabel")), e["year"], esc(KIND_LABELS.get(e.get("kind"), ""))),
             '<h2 class="card__title"><a class="card__link" href="%s">%s</a></h2>' % (esc(href), esc(title))]
    if e.get("titleJa") and e["titleJa"] != e["title"]:
        parts.append('<p class="card__original-title">%s</p>' % esc(e["title"]))
    org_line = " · ".join(x for x in [e.get("org"), i18n.country(e.get("country"))] if x)
    if org_line:
        parts.append('<p class="card__org">%s</p>' % esc(org_line))
    if langs:
        parts.append('<p class="card__langs">%s</p>' % esc("言語: " + langs))
    if langs_original:
        parts.append('<p class="card__original">%s</p>' % esc(langs_original))
    if cat == "dja":
        cats = sorted({category_ja(a.get("category", "")) for a in e.get("awards") or [] if a.get("category") is not None})
        if any(cats):
            parts.append('<p class="card__category">%s</p>' % esc(" · ".join(c for c in cats if c)))
    summary = e.get("summaryJa") or e.get("summary") or ""
    if summary:
        parts.append('<p class="card__summary">%s</p>' % esc(summary))
    if tags:
        parts.append('<div class="card__tags">%s</div>' % tags)
    parts.append('<div class="card__actions"><a class="card__detail" href="%s" data-id="%s">詳細</a>%s</div>' % (esc(href), esc(e["id"]), open_link))
    return '<article class="card" data-id="%s">\n          %s\n        </article>' % (esc(e["id"]), "\n          ".join(p for p in parts if p))


def embed_index(i18n, cat, text, entries, years, default_year):
    """Fill #card-grid and add the year index into the copied list page."""
    first = [e for e in entries if e["year"] == default_year][:PAGE_SIZE]
    total = sum(1 for e in entries if e["year"] == default_year)
    grid = '<div class="card-grid" id="card-grid">\n        %s\n        </div>' % "\n        ".join(render_card(i18n, cat, e) for e in first)
    text, n = re.subn(r'<div class="card-grid" id="card-grid">\s*</div>', lambda _m: grid, text, count=1)
    if n != 1:
        raise SystemExit("card-grid placeholder not found for %s" % cat)
    count = "%s年 1–%d件 / %d件" % (default_year, len(first), total) if total else "%s年 0件" % default_year
    text, n = re.subn(r'(<p id="result-count">)[^<]*(</p>)', lambda m: m.group(1) + count + m.group(2), text, count=1)
    if n != 1:
        raise SystemExit("result-count not found for %s" % cat)
    nav = year_nav(cat, years) + "\n\n    "
    text, n = re.subn(r'<footer class="site-footer">', lambda _m: nav + '<footer class="site-footer">', text, count=1)
    if n != 1:
        raise SystemExit("footer not found for %s" % cat)
    title = html.unescape(re.search(r"<title>(.*?)</title>", text, re.S).group(1).strip())
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', text, re.S)
    desc = html.unescape(m.group(1)) if m else ""
    canonical = SITE + CATALOGS[cat]["prefix"] + "/"
    meta = ['<link rel="canonical" href="%s" />' % esc(canonical)]
    for k, v in (("og:title", title), ("og:description", desc), ("og:url", canonical), ("og:type", "website")):
        if v:
            meta.append('<meta property="%s" content="%s" />' % (k, esc(v)))
    text, n = re.subn(r"</head>", lambda _m: "    " + "\n    ".join(meta) + "\n  </head>", text, count=1)
    if n != 1:
        raise SystemExit("</head> not found for %s" % cat)
    return text


# ---------------------------------------------------------------- main

def load_catalog(public, cat):
    conf = CATALOGS[cat]
    base = public / conf["data"]
    payload = json.loads((base / "entries.json").read_text(encoding="utf-8"))
    entries = sorted(payload["entries"], key=sort_key)
    details = {}
    for year in payload["years"]:
        p = base / ("details-%s.json" % year)
        details[year] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for e in entries:
        if not SAFE_ID.match(e["id"]):
            raise SystemExit("unsafe entry id: %r" % e["id"])
    return entries, sorted(payload["years"]), details


def default_year_for(index_file, years):
    """data-default-year of the list page; absent, "latest" or unknown means the newest year."""
    m = re.search(r'data-default-year="(\d+)"', index_file.read_text(encoding="utf-8"))
    year = int(m.group(1)) if m else None
    return year if year in years else max(years)


def build(public, out):
    public, out = public.resolve(), out.resolve()
    if out == public or public in out.parents or out in public.parents:
        raise SystemExit("output dir must be separate from the public dir")
    if out.exists():
        if not out.is_dir():
            raise SystemExit("output path is not a directory: %s" % out)
        if (out / MARKER).exists():
            shutil.rmtree(out)
        elif any(out.iterdir()):
            raise SystemExit("refusing to delete %s: no %s marker from a previous build" % (out, MARKER))
        else:
            out.rmdir()
    shutil.copytree(public, out)
    write(out / MARKER, "generated by scripts/build-pages.py; safe to delete\n")

    shell = Shell(public)
    i18n = I18n(public / "js" / "i18n.js")
    urls = [SITE + "/", SITE + "/dja/"]
    stats = {}
    for cat in CATALOGS:
        entries, years, details = load_catalog(public, cat)
        conf = CATALOGS[cat]
        by_year = {}
        for e in entries:
            by_year.setdefault(e["year"], []).append(e)
        for y in years:
            write(out / year_path(cat, y).strip("/") / "index.html", render_year_page(shell, i18n, cat, y, by_year.get(y, []), years))
            urls.append(SITE + year_path(cat, y))
        for e in entries:
            write(out / entry_path(cat, e["id"]).strip("/") / "index.html",
                  render_entry_page(shell, i18n, cat, e, details.get(e["year"], {}).get(e["id"]), years))
            urls.append(SITE + entry_path(cat, e["id"]))
        default_year = default_year_for(public / conf["index"], years)
        index_path = out / conf["index"]
        write(index_path, embed_index(i18n, cat, index_path.read_text(encoding="utf-8"), entries, years, default_year))
        stats[cat] = len(entries)

    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sitemap += ["  <url><loc>%s</loc></url>" % esc(u) for u in urls]
    sitemap.append("</urlset>")
    write(out / "sitemap.xml", "\n".join(sitemap) + "\n")
    return stats, len(urls)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="dist")
    ap.add_argument("--public-dir", default="public")
    args = ap.parse_args(argv)
    stats, n = build(Path(args.public_dir), Path(args.output_dir))
    print("built %s entries pages, %d sitemap urls -> %s" % (stats, n, args.output_dir))


if __name__ == "__main__":
    sys.exit(main())
