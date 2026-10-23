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

    def test_unk_ja_falls_back_to_original(self):
        src = json.loads((ROOT / "public/data/entries.json").read_text())["entries"]
        with_unk = [e for e in src if "<unk>" in (e.get("titleJa") or "")]
        self.assertTrue(with_unk)
        for e in with_unk:
            text = self.page("entries/" + e["id"])
            self.assertNotIn("&lt;unk&gt;", text)
            self.assertNotIn("<unk>", text)
            self.assertNotIn("alternateName", text, e["id"])
            self.assertIn("<h1>%s</h1>" % bp.esc(bp.clean_str(e["title"])), text, e["id"])
        text = self.page("entries/2020-s-0243")
        self.assertRegex(text, r"<title>„Die Welt bangt")
        self.assertIn("<h1>„Die Welt bangt", text)

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
        impact = json.loads((ROOT / "public/data/details-2020.json").read_text())["2020-s-0374"]["impact"]
        text = self.page("entries/2020-s-0374")
        self.assertIn("&amp=&feature=", impact)
        self.assertIn(h.escape(impact, quote=True), text)

    def test_bad_urls_not_linked(self):
        for i in ("2020-s-0031", "2020-s-0168", "2021-s-0423", "2020-s-0019", "2026-s-0045"):
            text = self.page("entries/" + i)
            ld = self.ld("entries/" + i)
            if i in ("2020-s-0031", "2020-s-0168", "2021-s-0423"):
                self.assertNotIn("url", ld, i)  # URL field carries a note after the address
            if "url" in ld:
                self.assertNotRegex(ld["url"], r"\s", i)
            for href in re.findall(r'<a [^>]*href="(https?://[^"]*)"', text.split("<main", 1)[1]):
                self.assertNotRegex(href, r"\s", i)

    def test_html_in_source_text(self):
        for i in ("2020-s-0091", "2021-s-0380"):
            text = self.page("entries/" + i)
            body = text.split('<div class="detail__body">', 1)[1].split("</article>", 1)[0]
            self.assertNotRegex(body, r"<(?:a|ul|h3)\b(?![^>]*(?:class|target))", i)
            self.assertIn("&lt;", body, i)
            ld = self.ld("entries/" + i)
            self.assertNotRegex(ld["description"], r"<[^>]+>")
            head = text.split("</head>", 1)[0]
            self.assertNotRegex(re.search(r"<title>(.*?)</title>", head).group(1), r"<")
            self.assertNotRegex(re.search(r'name="description" content="([^"]*)"', head).group(1), r"&lt;|<")

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
