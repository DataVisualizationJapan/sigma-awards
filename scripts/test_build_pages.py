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

INDEX = """<!DOCTYPE html><html><head><!-- Google tag (gtag.js) -->
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
        self.assertEqual(ld["name"], XSS)
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

    def test_rejects_output_inside_public(self):
        with self.assertRaises(SystemExit):
            bp.main(["--public-dir", str(self.public), "--output-dir", str(self.public / "x")])

    def test_unsafe_id_rejected(self):
        data = json.loads((self.public / "data/entries.json").read_text())
        data["entries"][1]["id"] = "../evil"
        write_json(self.public / "data/entries.json", data)
        with self.assertRaises(SystemExit):
            bp.main(["--public-dir", str(self.public), "--output-dir", str(self.tmp / "d3")])


if __name__ == "__main__":
    unittest.main()
