"""Tests for scripts/build-pages.py (static page generation)."""
import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts/build-pages.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

INDEX = """<!DOCTYPE html><html><head><title>T &amp; U</title><meta name="description" content="D" /><!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-X"></script>
<script>gtag('config', 'G-X');</script></head><body>
<p id="result-count">読み込み中</p>
<div class="card-grid" id="card-grid"></div>
<footer class="site-footer"><p>FOOT %s</p></footer></body></html>"""

XSS = '<script>alert(1)</script>"&'


def sigma_entry(i, year=2024, **kw):
    e = {"id": "%d-s-%04d" % (year, i), "year": year, "kind": "project", "title": "Title %d" % i, "org": "Org",
         "country": "Japan", "result": "entry", "resultLabel": "Entry", "tags": ["Map"], "summary": "s", "langs": "",
         "url": "https://example.com/%d" % i}
    e.update(kw)
    return e


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_public(root):
    (root / "dja").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "css/styles.css").write_text("body{}", encoding="utf-8")
    (root / "index.html").write_text(INDEX % "sigma", encoding="utf-8")
    (root / "dja/index.html").write_text(INDEX % "dja", encoding="utf-8")
    sigma = [
        sigma_entry(1, result="winner", resultLabel="Winner", title=XSS, org=XSS, titleJa="日本語 " + XSS,
                    summaryJa="要約 " + XSS, url="javascript:alert(1)", thumb="thumbs/a.png"),
        sigma_entry(2), sigma_entry(3, year=2025),
    ]
    write_json(root / "data/entries.json", {"years": [2024, 2025], "entries": sigma})
    write_json(root / "data/details-2024.json", {
        sigma[0]["id"]: {"summary": XSS, "impact": "imp", "links": ["https://example.com/ok", "ftp://bad", "javascript:x"]}})
    dja = [{"id": "dja-2019-aaaa", "year": 2019, "title": "Dja " + XSS, "org": "O", "country": "", "kind": "team",
            "result": "winner", "resultLabel": "winner", "tags": [], "langs": "", "summary": "", "summaryJa": "",
            "url": "", "awards": [{"category": "Cat " + XSS, "result": "winner"}],
            "sources": [{"file": "f.html", "original": "javascript:bad", "wayback": "https://web.archive.org/x"}],
            "thumb": "/thumbs/dja/x.png"}]
    write_json(root / "data/dja/entries.json", {"years": [2019], "entries": dja, "coverage": []})
    write_json(root / "data/dja/details-2019.json", {"dja-2019-aaaa": {"sourceRecords": [{"file": "f", "text": XSS}]}})
    return sigma, dja


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class BuildPagesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.public = self.tmp / "public"
        self.sigma, self.dja = make_public(self.public)
        self.out = self.tmp / "dist"
        bp.main(["--public-dir", str(self.public), "--output-dir", str(self.out)])

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_page_counts(self):
        self.assertEqual(len(list((self.out / "entries").glob("*/index.html"))), 3)
        self.assertEqual(len(list((self.out / "dja/entries").glob("*/index.html"))), 1)
        for rel in ("2024/index.html", "2025/index.html", "dja/2019/index.html"):
            self.assertTrue((self.out / rel).exists(), rel)

    def test_sitemap_parses_and_matches(self):
        root = ET.fromstring((self.out / "sitemap.xml").read_bytes())
        locs = [u[0].text for u in root]
        # /, /dja/, 3 year pages, 3 sigma + 1 dja entries
        self.assertEqual(len(locs), 2 + 3 + 4)
        self.assertEqual(len(set(locs)), len(locs))
        self.assertIn(bp.SITE + "/entries/2024-s-0001/", locs)
        self.assertIn(bp.SITE + "/dja/entries/dja-2019-aaaa/", locs)
        self.assertNotIn("lastmod", (self.out / "sitemap.xml").read_text())

    def test_json_ld_and_canonical(self):
        for rel, canon in (("entries/2024-s-0001/index.html", "/entries/2024-s-0001/"),
                           ("dja/entries/dja-2019-aaaa/index.html", "/dja/entries/dja-2019-aaaa/")):
            text = self.read(rel)
            blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
            self.assertEqual(len(blocks), 1)
            self.assertNotIn("<", blocks[0])
            ld = json.loads(blocks[0])
            self.assertEqual(ld["@type"], "CreativeWork")
            self.assertEqual(ld["mainEntityOfPage"], bp.SITE + canon)
            self.assertIn('<link rel="canonical" href="%s" />' % (bp.SITE + canon), text)
        ld = json.loads(re.search(r'ld\+json">(.*?)</script>', self.read("entries/2024-s-0001/index.html"), re.S).group(1))
        self.assertEqual(ld["name"], 'alert(1) "&')  # tags stripped in JSON-LD
        self.assertNotIn("url", ld)  # javascript: url is dropped
        self.assertEqual(ld["award"], "Sigma Awards 2024 Winner")

    def test_escaping_and_links(self):
        for rel in ("entries/2024-s-0001/index.html", "dja/entries/dja-2019-aaaa/index.html",
                    "2024/index.html", "index.html", "dja/2019/index.html"):
            text = self.read(rel)
            self.assertNotIn("<script>alert(1)</script>", text, rel)
            self.assertNotIn('href="javascript:', text, rel)
        text = self.read("entries/2024-s-0001/index.html")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn('href="https://example.com/ok"', text)
        self.assertNotIn("ftp://bad", text)
        self.assertIn('src="/thumbs/a.png"', text)
        self.assertIn(bp.SITE + "/thumbs/a.png", text)
        dja = self.read("dja/entries/dja-2019-aaaa/index.html")
        self.assertNotIn("javascript:bad", dja)
        self.assertIn("https://web.archive.org/x", dja)

    def rebuild_with(self, entry_patch, details):
        public = self.tmp / "public2"
        sigma, _ = make_public(public)
        entries = json.loads((public / "data/entries.json").read_text(encoding="utf-8"))
        entries["entries"][1].update(entry_patch)
        write_json(public / "data/entries.json", entries)
        write_json(public / "data/details-2024.json", {sigma[1]["id"]: details})
        out = self.tmp / "dist2"
        bp.main(["--public-dir", str(public), "--output-dir", str(out)])
        text = (out / "entries" / sigma[1]["id"] / "index.html").read_text(encoding="utf-8")
        ld = json.loads(re.search(r'ld\+json">(.*?)</script>', text, re.S).group(1))
        return text, ld

    def test_urls_with_notes_or_spaces_are_not_linked(self):
        text, ld = self.rebuild_with(
            {"url": "http://a.example/ (Original publication in French)"},
            {"summary": "s", "impact": "i", "links": [
                "http://a.example/ (Original publication in French)",
                "https://b.example/x https://c.example/y",
                "https://d.example/ok"]})
        self.assertNotIn("url", ld)
        self.assertIn('href="https://d.example/ok"', text)
        for href in re.findall(r'<a [^>]*href="([^"]*)"', text.split("<main", 1)[1]):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", href):
                self.assertRegex(href, r"^https?://\S+$")
        self.assertNotIn("a.example", text.split("<main", 1)[1])

    def test_paragraphs_refs_and_link_notes(self):
        xss = "<img src=x onerror=alert(1)>"
        text, ld = self.rebuild_with(
            {},
            {"summary": "first <b>\n\nsecond", "impact": "one\n\ntwo\n\nthree", "links": [
                "https://a.example/work", "https://b.example/other"],
             "refs": [{"url": "https://c.example/?a=1&b=2", "label": xss}, {"url": "https://d.example/x", "label": ""},
                      {"url": "javascript:alert(1)", "label": "bad"}, {"url": "ftp://e.example/", "label": "ftp"}],
             "linkNotes": {"https://a.example/work": "Passcode: <x>&1", "https://zzz.example/": "stray"},
             "summaryJa": "第一\n\n第二", "impactJa": "一"})
        main = text.split("<main", 1)[1]
        self.assertIn("<h2>概要</h2><p>第一</p><p>第二</p>", main)
        self.assertIn("<h2>概要</h2><p>first &lt;b&gt;</p><p>second</p>", main)  # the 原文 section
        self.assertIn("<h2>影響</h2><p>一</p>", main)
        self.assertIn("<h2>影響</h2><p>one</p><p>two</p><p>three</p>", main)
        self.assertIn('<span class="link-row"><a href="https://a.example/work" target="_blank" rel="noopener noreferrer">作品を開く</a>'
                      '<small class="link-note">Passcode: &lt;x&gt;&amp;1</small></span>', main)
        self.assertIn('<span class="link-row"><a href="https://b.example/other" target="_blank" rel="noopener noreferrer">'
                      'https://b.example/other</a></span>', main)
        self.assertNotIn("stray", main)
        refs = main.split('<h2 class="ref-title">本文中のリンク</h2>', 1)[1].split("</ul>", 1)[0]
        self.assertEqual(re.findall(r'href="([^"]*)"', refs), ["https://c.example/?a=1&amp;b=2", "https://d.example/x"])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;</a>", refs)
        self.assertIn(">https://d.example/x</a>", refs)
        self.assertNotIn("<img src=x", main)
        self.assertNotIn("javascript:", main)
        self.assertNotIn("ftp://", main)
        self.assertEqual(ld["description"], "第一 第二")

    def test_no_refs_section_without_refs(self):
        text, _ = self.rebuild_with({}, {"summary": "s", "impact": "i", "links": ["https://a.example/work"], "refs": []})
        self.assertNotIn("本文中のリンク", text.split("<main", 1)[1])
        self.assertNotIn("link-note", text.split("<main", 1)[1])

    def test_unk_ja_falls_back_to_original(self):
        text, ld = self.rebuild_with(
            {"title": "„Die Welt bangt", "titleJa": "<unk>Die Welt bangt // <unk> 世界は恐れる",
             "summaryJa": "吸うこと <unk>酒"},
            {"summary": "orig summary", "impact": "i", "links": [], "summaryJa": "吸うこと <unk>酒",
             "impactJa": "We<unk>ve", "juryJa": "<unk>"})
        for needle in ("&lt;unk&gt;", "<unk>"):
            self.assertNotIn(needle, text)
        self.assertNotIn("alternateName", text)
        self.assertNotIn("alternateName", ld)
        self.assertIn("<h1>%s</h1>" % bp.esc(bp.clean_str("„Die Welt bangt")), text)

    def test_index_embeds_cards(self):
        # 2026 is absent from the fixture, so the latest available year (2025) is embedded
        self.assertIn('<h2 class="card__title"><a class="card__link" href="/entries/2025-s-0003/">Title 3</a></h2>', self.read("index.html"))
        self.assertIn('<a class="card__detail" href="/entries/2025-s-0003/" data-id="2025-s-0003">詳細</a>', self.read("index.html"))
        text = self.read("index.html")
        self.assertIn('<nav class="year-index"', text)
        self.assertIn("年別一覧", text)
        self.assertLess(text.index("年別一覧"), text.index('<footer class="site-footer">'))
        dja = self.read("dja/index.html")
        self.assertIn('<a class="card__detail" href="/dja/entries/dja-2019-aaaa/" data-id="dja-2019-aaaa">詳細</a>', dja)
        self.assertIn('href="/dja/2019/"', dja)

    def test_deterministic_and_public_untouched(self):
        before = tree_hash(self.public)
        out2 = self.tmp / "dist2"
        bp.main(["--public-dir", str(self.public), "--output-dir", str(out2)])
        self.assertEqual(tree_hash(self.out), tree_hash(out2))
        self.assertEqual(before, tree_hash(self.public))

    def test_unescape_once_is_conservative(self):
        for keep in ("?a=1&para=2", "&copy=", "&amp=&feature=", "x&times"):
            self.assertEqual(bp.unescape_once(keep), keep)
        self.assertEqual(bp.unescape_once("A &amp; B &lt;i&gt; &#38; &#x26; &quot;"), 'A & B <i> & & "')
        self.assertEqual(bp.unescape_once("&amp;amp;"), "&amp;")  # one pass only
        self.assertEqual(bp.unescape_once("a&amp;para=1"), "a&para=1")

    def test_plain_strips_only_html_tags(self):
        self.assertEqual(bp.plain("a <b>x</b> <!-- c --> <Роскомнадзор> d <3"), "a x <Роскомнадзор> d <3")

    def test_refuses_unmarked_existing_output(self):
        victim = self.tmp / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("x")
        with self.assertRaises(SystemExit):
            bp.main(["--public-dir", str(self.public), "--output-dir", str(victim)])
        self.assertTrue((victim / "keep.txt").exists())
        bp.main(["--public-dir", str(self.public), "--output-dir", str(self.out)])  # marked: rebuilt
        empty = self.tmp / "empty"
        empty.mkdir()
        bp.main(["--public-dir", str(self.public), "--output-dir", str(empty)])
        self.assertTrue((empty / bp.MARKER).exists())

    def test_default_year_from_index_attribute(self):
        idx = self.public / "index.html"
        idx.write_text(idx.read_text().replace("<body>", '<body data-default-year="2024">'), encoding="utf-8")
        out = self.tmp / "d4"
        bp.main(["--public-dir", str(self.public), "--output-dir", str(out)])
        text = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("2024年 1–2件 / 2件", text)
        self.assertIn('data-id="2024-s-0002"', text)
        self.assertNotIn('data-id="2025-s-0003"', text)

    def test_rejects_output_inside_public(self):
        with self.assertRaises(SystemExit):
            bp.main(["--public-dir", str(self.public), "--output-dir", str(self.public / "x")])

    def test_unsafe_id_rejected(self):
        data = json.loads((self.public / "data/entries.json").read_text())
        data["entries"][1]["id"] = "../evil"
        write_json(self.public / "data/entries.json", data)
        with self.assertRaises(SystemExit):
            bp.main(["--public-dir", str(self.public), "--output-dir", str(self.tmp / "d3")])


class CategoryJaTests(unittest.TestCase):
    def test_expected_values(self):
        self.assertEqual(bp.category_ja("Data visualisation of the year (small newsroom, large newsroom)"),
                         "データ可視化 (小規模編集部, 大規模編集部)")
        self.assertEqual(bp.category_ja("Small Newsroom"), "小規模編集部")
        self.assertEqual(bp.category_ja("Largest award"), "Largest award")
        self.assertEqual(bp.category_ja("small媒体"), "小規模編集部媒体")
        self.assertEqual(bp.category_ja(None), "")
        self.assertEqual(bp.category_ja(""), "")

    def test_matches_js_for_all_dja_categories(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node not available")
        entries = json.loads((ROOT / "public/data/dja/entries.json").read_text(encoding="utf-8"))["entries"]
        cats = sorted({a["category"] for e in entries for a in e.get("awards") or [] if a.get("category") is not None})
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const fn = src.match(/function categoryJa\(value\) \{[\s\S]*?\n\}\n/)[0];
const IS_DJA = true;
const categoryJa = eval('(' + fn.replace('function categoryJa', 'function') + ')');
const cats = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(cats.map(categoryJa)));
"""
        r = subprocess.run(["node", "-e", js, str(ROOT / "public/js/app.js")], input=json.dumps(cats),
                           capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(r.stdout), [bp.category_ja(c) for c in cats])
        self.assertGreater(len(cats), 50)

    def run_js(self, fn_name, values):
        import subprocess
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const m = src.match(new RegExp('function ' + process.argv[2] + '\\([^)]*\\) \\{[\\s\\S]*?\\n\\}\\n'))[0];
const IS_DJA = true;
const f = eval('(' + m.replace('function ' + process.argv[2], 'function') + ')');
console.log(JSON.stringify(JSON.parse(fs.readFileSync(0, 'utf8')).map(f)));
"""
        r = subprocess.run(["node", "-e", js, str(ROOT / "public/js/app.js"), fn_name], input=json.dumps(values),
                           capture_output=True, text=True, check=True)
        return json.loads(r.stdout)

    def test_matches_js_next_to_japanese_text(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not available")
        samples = ["small媒体", "large編集部", "Small newsroom", "small newsroom、large newsroom", "xsmall", "small_x",
                   "Data (large)", "ÉlargeÉ", "Largest", "本small本"]
        self.assertEqual(self.run_js("categoryJa", samples), [bp.category_ja(c) for c in samples])

    def test_http_url_matches_js_for_all_sigma_links(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not available")
        urls = set(["", "ftp://x.org/a", "javascript:alert(1)", "http://a b.com", "https://x.org/a b", "https://ok.org/p"])
        for e in json.loads((ROOT / "public/data/entries.json").read_text(encoding="utf-8")).get("entries", []):
            if e.get("url"):
                urls.add(e["url"])
        for f in (ROOT / "public/data").glob("details-*.json"):
            for d in json.loads(f.read_text(encoding="utf-8")).values():
                urls.update(u for u in (d.get("links") or []) if isinstance(u, str))
        urls = sorted(urls)
        self.assertGreater(len(urls), 1000)
        got, want = self.run_js("isHttpUrl", urls), [bool(bp.http_url(u)) for u in urls]
        self.assertEqual([(u, g) for u, g, w in zip(urls, got, want) if g != w], [])


class RealDataTests(unittest.TestCase):
    """Checks against known problem records in the committed catalog."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        bp.main(["--public-dir", str(ROOT / "public"), "--output-dir", str(cls.out)])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def page(self, rel):
        return (self.out / rel / "index.html").read_text(encoding="utf-8")

    def ld(self, rel):
        return json.loads(re.search(r'ld\+json">(.*?)</script>', self.page(rel), re.S).group(1))

    def test_counts(self):
        self.assertEqual(len(list((self.out / "entries").glob("*/index.html"))), 3899)
        self.assertEqual(len(list((self.out / "dja/entries").glob("*/index.html"))), 535)

    def test_quoted_title_shown_in_full(self):
        text = self.page("entries/2020-s-0243")
        self.assertRegex(text, r"<title>„Die Welt bangt")
        self.assertIn("<h1>„Die Welt bangt", text)
        self.assertNotIn("&lt;unk&gt;", text)

    def test_placeholder_org_authors_tools(self):
        text = self.page("entries/2020-f-0052")
        self.assertNotRegex(text, r'detail__org">\s*None')
        self.assertNotIn("author", self.ld("entries/2020-f-0052"))
        text = self.page("entries/2022-s-0195")
        self.assertNotIn("<h2>制作</h2>", text)
        self.assertIn("<h2>使った技術</h2>", text)

    def test_list_pages_have_canonical_and_og(self):
        for rel, url in (("", bp.SITE + "/"), ("dja", bp.SITE + "/dja/")):
            head = self.page(rel).split("</head>", 1)[0]
            self.assertIn('<link rel="canonical" href="%s" />' % url, head)
            for k in ("og:title", "og:description", "og:url", "og:type"):
                self.assertIn('property="%s"' % k, head)
            self.assertIn('<meta property="og:type" content="website" />', head)

    def test_aria_current_page(self):
        text = self.page("entries/2020-s-0001")
        self.assertIn('<a href="/" aria-current="page">Sigma Awards</a>', text)
        self.assertNotIn('aria-current="true"', text)

    def test_entities_not_double_escaped(self):
        text = self.page("entries/2024-s-0056")
        self.assertIn("Climate Crisis &amp; You", text)
        self.assertNotIn("&amp;amp;", text)
        self.assertEqual(self.ld("entries/2024-s-0056")["name"], "Unsettled Debt: Africa, The Climate Crisis & You")

    def test_semicolonless_ampersand_sequences_kept(self):
        import html as h
        entries = {e["id"]: e for e in json.loads((ROOT / "public/data/entries.json").read_text())["entries"]}
        for i in ("2022-s-0191", "2022-s-0194", "2022-s-0339"):
            details = json.loads((ROOT / ("public/data/details-%s.json" % i[:4])).read_text())[i]
            text = self.page("entries/" + i)
            hrefs = [h.unescape(x) for x in re.findall(r'<a [^>]*href="([^"]*)"', text.split("<main", 1)[1])]
            for url in details["links"]:
                self.assertIn(url, hrefs, i)
            if entries[i]["url"]:
                self.assertEqual(self.ld("entries/" + i)["url"], entries[i]["url"])
        self.assertIn("&amp;timestamp=55963", self.page("entries/2022-s-0191"))
        refs = json.loads((ROOT / "public/data/details-2020.json").read_text())["2020-s-0374"]["refs"]
        url = next(ref["url"] for ref in refs if "&amp=&feature=" in ref["url"])
        text = self.page("entries/2020-s-0374")
        self.assertIn(h.escape(url, quote=True), text)

    def test_urls_in_output_are_http_without_whitespace(self):
        for i in ("2020-s-0031", "2020-s-0168", "2021-s-0423", "2020-s-0019", "2026-s-0045"):
            text = self.page("entries/" + i)
            ld = self.ld("entries/" + i)
            if "url" in ld:
                self.assertRegex(ld["url"], r"^https?://\S+$", i)
            for href in re.findall(r'<a [^>]*href="([^"]*)"', text.split("<main", 1)[1]):
                if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", href):
                    self.assertRegex(href, r"^https?://\S+$", i)

    def test_html_in_source_text(self):
        for i in ("2020-s-0091", "2021-s-0380"):
            text = self.page("entries/" + i)
            body = text.split('<div class="detail__body">', 1)[1].split("</article>", 1)[0]
            self.assertNotRegex(body, r"<(?:a|ul|h3)\b(?![^>]*(?:class|target))", i)
            self.assertNotIn("&lt;", body, i)
            ld = self.ld("entries/" + i)
            self.assertNotRegex(ld["description"], r"<[^>]+>")
            head = text.split("</head>", 1)[0]
            self.assertNotRegex(re.search(r"<title>(.*?)</title>", head).group(1), r"<")
            self.assertNotRegex(re.search(r'name="description" content="([^"]*)"', head).group(1), r"&lt;|<")
        self.assertIn("#WildEye is a pioneering", self.page("entries/2020-s-0091"))
        self.assertIn("non-dairy, etc.), and countries", self.page("entries/2021-s-0380"))

    def test_paragraphs_refs_and_notes_from_real_data(self):
        text = self.page("entries/2020-s-0130")
        self.assertRegex(text, r"<p>Dallas</p>\s*<p>https://www\.dallasnews\.com/\S+ https://www\.dmagazine\.com/")
        self.assertGreaterEqual(text.count("<p>"), 8)
        self.assertNotRegex(text, r"<p>[^<]*\n\n")
        refs = text.split('<h2 class="ref-title">本文中のリンク</h2>', 1)[1].split("</ul>", 1)[0]
        self.assertIn('<li><a href="https://daac.ornl.gov/cgi-bin/dsviewer.pl?ds_id=1735" target="_blank" rel="noopener noreferrer">'
                      'Database of Road Transportation Emissions</a></li>', refs.replace("&amp;", "&"))
        self.assertIn('<li><a href="https://www.king5.com/article/news/local/vehicle-emissions-rise-in-seattle-metro-areas/'
                      '281-e2454541-a1db-4373-b1e2-6f7477f6a92c" target="_blank" rel="noopener noreferrer">https://www.king5.com/', refs)
        zoom = self.page("entries/2022-s-0269")
        self.assertRegex(zoom, r'<span class="link-row"><a href="https://kqed\.zoom\.us/rec/play/[^"]+" target="_blank" '
                               r'rel="noopener noreferrer">https://kqed\.zoom\.us/[^<]+</a><small class="link-note">Passcode: \^6@V#ytf</small></span>')

    def test_thumbs_resolve(self):
        text = self.page("entries/2023-s-0001")
        self.assertIn('src="/thumbs/2023-s-0001.png"', text)
        self.assertIn(bp.SITE + "/thumbs/2023-s-0001.png", text)
        dja = json.loads((ROOT / "public/data/dja/entries.json").read_text())["entries"]
        e = next(x for x in dja if x.get("thumb"))
        text = self.page("dja/entries/" + e["id"])
        self.assertIn('src="%s"' % e["thumb"], text)
        self.assertIn(bp.SITE + e["thumb"], text)

    def test_no_empty_elements(self):
        for rel in ("entries/2020-s-0001", "dja/entries/dja-2019-84be5da5830d", "dja"):
            text = self.page(rel)
            if rel != "dja":  # list pages keep empty containers that app.js fills
                self.assertNotRegex(text, r"<(p|div|h2)\b[^>]*>\s*</\1>", rel)
            else:
                grid = text.split('id="card-grid">', 1)[1].split('<p class="empty"', 1)[0]
                self.assertNotRegex(grid, r"<(p|div|h2)\b[^>]*>\s*</\1>")
            self.assertNotRegex(text, r'content=""', rel)
            self.assertNotRegex(text, r'<[^>]*href=""', rel)
        ld = self.ld("dja/entries/dja-2019-84be5da5830d")
        self.assertNotIn("url", ld)
        self.assertNotIn("alternateName", ld)
        self.assertNotIn("license", ld)
        self.assertTrue(all(v not in ("", [], None) for v in ld.values()))

    def test_dja_has_no_cc_license(self):
        for rel in ("dja/entries/dja-2019-84be5da5830d", "dja"):
            self.assertNotIn("CC BY-NC-SA", self.page(rel))
        self.assertIn("CC BY-NC-SA", self.page("entries/2020-s-0001"))


if __name__ == "__main__":
    unittest.main()
