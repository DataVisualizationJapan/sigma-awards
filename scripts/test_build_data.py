#!/usr/bin/env python3
"""Checks for the Sigma Awards text clean-up rules and the generated catalog JSON."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sigma_text import (  # noqa: E402
    blank_placeholder,
    decode_csv_bytes,
    decode_entities,
    is_valid_url,
    normalize_links,
    normalize_url_cell,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
BASIC_ENTITY = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
PLACEHOLDERS = {"none", "n/a", "na", "nil", "nil.", "-", "—"}


class DecodeEntitiesTest(unittest.TestCase):
    def test_basic_entities(self) -> None:
        self.assertEqual(decode_entities("Climate Crisis &amp; You"), "Climate Crisis & You")
        self.assertEqual(decode_entities("&lt;b&gt; &quot;x&quot; it&apos;s"), "<b> \"x\" it's")
        self.assertEqual(decode_entities("&#39;a&#x27;b"), "'a'b")

    def test_decodes_once(self) -> None:
        self.assertEqual(decode_entities("&amp;amp;"), "&amp;")

    def test_urls_without_semicolon_are_unchanged(self) -> None:
        for text in (
            "?a=1&para=2",
            "https://x.example/p?a=1&copy=2",
            "https://x.example/?&amp=&feature=share",
            "https://my-h5news.app.xinhuanet.com/a/?id=af27&timestamp=55963",
            "https://www.bilibili.com/video/BV1?p=1&share_medium=iphone&share_plat=ios",
            "a &times b",
        ):
            self.assertEqual(decode_entities(text), text)

    def test_invalid_numeric_references_are_kept(self) -> None:
        for text in ("&#0;", "&#xD800;", "&#99999999999;"):
            self.assertEqual(decode_entities(text), text)


class PlaceholderTest(unittest.TestCase):
    def test_placeholders_become_empty(self) -> None:
        for value in ("None", "none", " NONE ", "N/A", "n/a", "NA", "Nil.", "nil", "-", "—"):
            self.assertEqual(blank_placeholder(value), "", value)

    def test_real_text_is_kept(self) -> None:
        for value in ("None of us were told", "Nigeria", "N/A (see below)", "Python"):
            self.assertEqual(blank_placeholder(value), value)


class DecodeCsvBytesTest(unittest.TestCase):
    def test_bad_line_falls_back_to_mac_roman(self) -> None:
        data = b'\xef\xbb\xbfa,b\n"told, \xd2You\xd3 and \xd5s",ok\n\xe3\x81\x82,2\n'
        text = decode_csv_bytes(data)
        self.assertEqual(text, 'a,b\n"told, “You” and ’s",ok\nあ,2\n')


    def test_mixed_utf8_and_invalid_line_stops(self) -> None:
        data = b'a,b\n"caf\xc3\xa9 \xd2x",1\n'
        with self.assertRaises(SystemExit) as raised:
            decode_csv_bytes(data, "projects.csv")
        self.assertIn("projects.csv", str(raised.exception))
        self.assertIn("line 2", str(raised.exception))

    def test_mac_roman_only_line_is_read(self) -> None:
        self.assertEqual(decode_csv_bytes(b"a\n\xd2You\xd3\n"), "a\n\u201cYou\u201d\n")


class NormalizeUrlTest(unittest.TestCase):
    def urls(self, raw: str) -> list[str]:
        return normalize_url_cell(raw)[0]

    def test_description_after_url(self) -> None:
        self.assertEqual(
            self.urls("http://medor-opioids.s3-website-eu-west-1.amazonaws.com/ (Translation in english of the original publication)"),
            ["http://medor-opioids.s3-website-eu-west-1.amazonaws.com/"],
        )
        self.assertEqual(
            self.urls("https://australiatalks.abc.net.au/results/2ba0 [indicative results page]"),
            ["https://australiatalks.abc.net.au/results/2ba0"],
        )
        self.assertEqual(
            self.urls('http://bit.ly/va-hmda-methodology -- "Nerd box" explaining where I got the data.'),
            ["http://bit.ly/va-hmda-methodology"],
        )
        self.assertEqual(
            self.urls("https://pandemiainvisible.lalupa.press (This link has a plugin so you can read it)"),
            ["https://pandemiainvisible.lalupa.press"],
        )

    def test_dropped_fragments_are_reported(self) -> None:
        urls, dropped = normalize_url_cell("https://a.example/x (note one) (note two)")
        self.assertEqual(urls, ["https://a.example/x"])
        self.assertEqual(dropped, ["(note one) (note two)"])

    def test_space_separated_urls(self) -> None:
        self.assertEqual(
            self.urls("https://sverigesradio.se/sida/artikel.aspx?programid=185&artikel=7160785 https://yle.fi/uutiset/3-10662005"),
            ["https://sverigesradio.se/sida/artikel.aspx?programid=185&artikel=7160785", "https://yle.fi/uutiset/3-10662005"],
        )
        self.assertEqual(
            self.urls("https://www.dataphyte.com/latest-reports/governance/suspicious https://www.dataphyte.com/latest-reports/x/"),
            ["https://www.dataphyte.com/latest-reports/governance/suspicious", "https://www.dataphyte.com/latest-reports/x/"],
        )

    def test_concatenation_without_space(self) -> None:
        self.assertEqual(
            self.urls("https://www.usatoday.com/story/a/7876434002/https://www.usatoday.com/in-depth/b/5333761001/"),
            ["https://www.usatoday.com/story/a/7876434002/", "https://www.usatoday.com/in-depth/b/5333761001/"],
        )

    def test_markdown(self) -> None:
        self.assertEqual(
            self.urls("https://www.rtve.es/n/2239980.shtml](https://www.rtve.es/n/2239980.shtml"),
            ["https://www.rtve.es/n/2239980.shtml", "https://www.rtve.es/n/2239980.shtml"],
        )
        self.assertEqual(self.urls("https://a.example/x [t](https://b.example/y)"), ["https://a.example/x", "https://b.example/y"])

    def test_prose_is_dropped(self) -> None:
        urls, dropped = normalize_url_cell("https://Death brokers in Gaza: Medication Contains Lethal Toxin By: Roaa")
        self.assertEqual(urls, [])
        self.assertEqual(len(dropped), 1)

    def test_wrapped_urls_are_not_split(self) -> None:
        for url in (
            "https://translate.google.com/translate?sl=auto&tl=en&u=https://www.contexte.com/article/x.html",
            "https://web.archive.org/web/20200415030216/https://apps.texastribune.org/features/2020/map/",
            "https://web.archive.org/web/20221001120424/https://arij.net/investigations/electricity-egypt-en/",
            "https://web.archive.org/web/20231021005121/https://elpais.com/clima/a.html",
            "https://www.google.com/url?q=https://cnsmaryland.org/2023/10/12/books/&source=gmail&ust=1705430088835000",
            "https://l.facebook.com/l.php?u=https%3A%2F%2Farij.net%2Fa",
        ):
            self.assertEqual(self.urls(url), [url])

    def test_text_fragment_is_kept(self) -> None:
        url = "https://armando.info/oro/#:~:text=Un%20esquema%20que%20involucra%20a,terminaron%20en%20el%20mercado%20global."
        self.assertEqual(self.urls(url), [url])

    def test_entities_in_links(self) -> None:
        self.assertEqual(
            self.urls("https://www.google.com/url?q=https://a.example/b/&amp;source=gmail&amp;usg=AO"),
            ["https://www.google.com/url?q=https://a.example/b/&source=gmail&usg=AO"],
        )
        for url in (
            "https://my-h5news.app.xinhuanet.com/xhh-pc/article/?id=af27&timestamp=55963",
            "https://www.bilibili.com/video/BV1?p=1&share_medium=iphone&timestamp=1642088557",
        ):
            self.assertEqual(self.urls(url), [url])

    def test_trailing_punctuation_and_brackets(self) -> None:
        self.assertEqual(self.urls("https://www.landgrabu.org/. This is link to overview"), ["https://www.landgrabu.org/"])
        self.assertEqual(self.urls("https://a.example/x,"), ["https://a.example/x"])
        self.assertEqual(self.urls("https://a.example/x)"), ["https://a.example/x"])
        self.assertEqual(self.urls("https://a.example/x]"), ["https://a.example/x"])
        for url in (
            "https://www.thelancet.com/journals/laninf/article/PIIS1473-3099(20)30785-4/fulltext",
            "https://en.wikipedia.org/wiki/Foo_(bar)",
            "https://www.reuters.com/HEALTH/HERD%20IMMUNITY%20(EXPLAINER)/gjnvwayydvw/",
        ):
            self.assertEqual(self.urls(url), [url])

    def test_validation(self) -> None:
        self.assertFalse(is_valid_url("https://Death"))
        self.assertFalse(is_valid_url("ftp://a.example/x"))
        self.assertFalse(is_valid_url("https://a.example/x y"))
        self.assertTrue(is_valid_url("http://a.example"))

    def test_dedupe_keeps_order(self) -> None:
        links, fixes = normalize_links(["https://a.example/1", "https://b.example/2 (x)", "https://a.example/1"])
        self.assertEqual(links, ["https://a.example/1", "https://b.example/2"])
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["dropped"], ["(x)"])


ROOT = Path(__file__).resolve().parents[1]


def load_build_module():
    spec = importlib.util.spec_from_file_location("build_data", ROOT / "scripts" / "build-data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildOutputTest(unittest.TestCase):
    """Rebuilding must give byte-identical JSON whatever key order the previous output had."""

    def test_rebuild_is_byte_identical_with_fixed_key_order(self) -> None:
        source = ROOT / ".tmp-data"
        if not (source / "The Sigma Awards 2026-single-project.csv").exists():
            self.skipTest("upstream data not cloned in .tmp-data")
        build = load_build_module()

        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2000, 1, 1, tzinfo=tz)

        saved = (build.OUT_DIR, build.SOURCE_DIR, build.datetime, build.id_ledger.save)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for path in DATA_DIR.glob("*.json"):
                if path.is_file():
                    shutil.copy(path, out / path.name)
            # Scramble key order so only the build decides the output order.
            for path in out.glob("details-*.json"):
                doc = json.loads(path.read_text(encoding="utf-8"))
                scrambled = {i: dict(reversed(list(rec.items()))) for i, rec in doc.items()}
                path.write_text(json.dumps(scrambled, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            build.OUT_DIR, build.SOURCE_DIR, build.datetime = out, source, FixedClock
            build.id_ledger.save = lambda ledger: None
            try:
                runs = []
                for _ in range(2):
                    with unittest.mock.patch("builtins.print"):
                        build.build()
                    runs.append({p.name: p.read_bytes() for p in sorted(out.glob("*.json"))})
            finally:
                build.OUT_DIR, build.SOURCE_DIR, build.datetime, build.id_ledger.save = saved
            self.assertEqual(runs[0], runs[1])
            for name, data in runs[0].items():
                if name.startswith("details-"):
                    self.assertEqual(data, (DATA_DIR / name).read_bytes(), name)


def walk_strings(node: object, path: str = ""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_strings(value, f"{path}[{index}]")


class GeneratedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries_doc = json.loads((DATA_DIR / "entries.json").read_text(encoding="utf-8"))
        cls.entries = cls.entries_doc["entries"]
        cls.details: dict[str, dict] = {}
        cls.detail_files = sorted(DATA_DIR.glob("details-*.json"))
        for path in cls.detail_files:
            cls.details.update(json.loads(path.read_text(encoding="utf-8")))

    def documents(self):
        yield "entries.json", self.entries_doc
        for path in self.detail_files:
            yield path.name, json.loads(path.read_text(encoding="utf-8"))

    def test_ids_match_between_files(self) -> None:
        ids = [entry["id"] for entry in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(self.details))
        self.assertEqual(self.entries_doc["count"], len(ids))

    def test_no_unk_entity_or_replacement_character(self) -> None:
        for name, doc in self.documents():
            for path, text in walk_strings(doc):
                self.assertNotIn("<unk>", text, f"{name}{path}")
                self.assertNotIn("�", text, f"{name}{path}")
                self.assertIsNone(BASIC_ENTITY.search(text), f"{name}{path}: {text[:80]}")

    def test_links_are_valid(self) -> None:
        for entry_id, record in self.details.items():
            self.assertEqual(len(record["links"]), len(set(record["links"])), entry_id)
            for url in record["links"]:
                self.assertTrue(is_valid_url(url), f"{entry_id}: {url[:100]}")
        for entry in self.entries:
            links = self.details[entry["id"]]["links"]
            self.assertEqual(entry["url"], links[0] if links else "", entry["id"])

    def test_no_placeholder_values(self) -> None:
        for entry in self.entries:
            for field in ("org", "country"):
                self.assertNotIn(entry[field].strip().lower(), PLACEHOLDERS, f"{entry['id']} {field}")
        for entry_id, record in self.details.items():
            for field in ("authors", "tools", "impact"):
                self.assertNotIn(record[field].strip().lower(), PLACEHOLDERS, f"{entry_id} {field}")

    def test_known_fixes(self) -> None:
        by_id = {entry["id"]: entry for entry in self.entries}
        self.assertEqual(by_id["2024-s-0056"]["title"], "Unsettled Debt: Africa, The Climate Crisis & You")
        self.assertEqual(by_id["2024-s-0058"]["country"], "")
        self.assertEqual(by_id["2020-f-0052"]["org"], "")
        self.assertEqual(self.details["2022-s-0195"]["authors"], "")
        self.assertEqual(self.details["2025-s-0309"]["impact"], "")
        self.assertIn("“You have described", self.details["2023-s-0003"]["impact"])
        self.assertTrue(any("&timestamp=" in url for url in self.details["2022-s-0191"]["links"]))
        self.assertEqual(self.details["2026-s-0045"]["links"][-1:], [self.details["2026-s-0045"]["links"][-1]])
        self.assertEqual(len(self.details["2022-f-0058"]["links"]), 4)

    def test_url_fixes_log(self) -> None:
        log = json.loads((DATA_DIR / "url-fixes.json").read_text(encoding="utf-8"))
        self.assertEqual(log["count"], len(log["fixes"]))
        for fix in log["fixes"]:
            self.assertEqual(set(fix), {"id", "field", "original", "result", "dropped"})
            self.assertIn(fix["id"], self.details)


if __name__ == "__main__":
    unittest.main()
