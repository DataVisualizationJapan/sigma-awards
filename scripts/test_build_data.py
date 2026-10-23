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
    KNOWN_TAGS,
    blank_placeholder,
    collect_link_notes,
    decode_csv_bytes,
    decode_entities,
    find_tag_like,
    html_to_text,
    is_valid_url,
    merge_refs,
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


class HtmlToTextTest(unittest.TestCase):
    """Rules for turning tags and Markdown in free-text fields into paragraphs and refs."""

    def test_anchor_keeps_label_and_lists_url(self) -> None:
        text, refs = html_to_text('<a href="https://oxpeckers.org/wildeyemap/">#WildEye</a> is a pioneering tool')
        self.assertEqual(text, "#WildEye is a pioneering tool")
        self.assertEqual(refs, [{"url": "https://oxpeckers.org/wildeyemap/", "label": "#WildEye"}])

    def test_comments_vanish_without_spaces(self) -> None:
        self.assertEqual(
            html_to_text("non-<!-- -->dairy<!-- -->, etc.), <!-- -->and countries")[0],
            "non-dairy, etc.), and countries",
        )

    def test_inline_tags_add_no_space(self) -> None:
        self.assertEqual(html_to_text("69<sup>th</sup> place")[0], "69th place")
        self.assertEqual(html_to_text("<b>A</b><i>B</i><span>C</span><code>D</code>")[0], "ABCD")

    def test_block_tags_split_paragraphs(self) -> None:
        text, refs = html_to_text(
            'emissions. <h4> Dallas </h4> <ul> <a href="https://a.example/1">https://a.example/1</a>'
            ' <a href="https://b.example/2">https://b.example/2</a> </ul>'
        )
        self.assertEqual(text, "emissions.\n\nDallas\n\nhttps://a.example/1 https://b.example/2")
        self.assertEqual([ref["url"] for ref in refs], ["https://a.example/1", "https://b.example/2"])
        self.assertEqual([ref["label"] for ref in refs], ["", ""])
        for tag in ("br", "p", "div", "h1", "h6", "ul", "ol", "li", "pre", "hr", "blockquote", "table", "tr"):
            self.assertEqual(html_to_text(f"a<{tag}>b</{tag}>c")[0], "a\n\nb\n\nc", tag)

    def test_unclosed_anchor_keeps_following_text(self) -> None:
        text, refs = html_to_text('(<a href="https://www1.folha.uol.com.br/x/y.shtml">https://www1.folha.uol.com.br/x/y.shtml).')
        self.assertEqual(text, "(https://www1.folha.uol.com.br/x/y.shtml).")
        self.assertEqual(refs, [{"url": "https://www1.folha.uol.com.br/x/y.shtml", "label": ""}])
        text, refs = html_to_text('level ), <a href="https://web.archive.org/web/1/selangor">district and subdistrict level ),')
        self.assertEqual(text, "level ), district and subdistrict level ),")
        self.assertEqual(refs, [{"url": "https://web.archive.org/web/1/selangor", "label": ""}])

    def test_unclosed_anchor_does_not_swallow_the_next_one(self) -> None:
        text, refs = html_to_text('<a href="https://a.example/">one <a href="https://b.example/">two</a>')
        self.assertEqual(text, "one two")
        self.assertEqual(refs, [{"url": "https://a.example/", "label": ""}, {"url": "https://b.example/", "label": "two"}])

    def test_label_equal_to_url_is_blank(self) -> None:
        _, refs = html_to_text('<a href="https://a.example/x/">https://a.example/x</a>')
        self.assertEqual(refs, [{"url": "https://a.example/x/", "label": ""}])

    def test_invalid_urls_are_not_listed(self) -> None:
        text, refs = html_to_text('<a href="javascript:alert(1)">x</a> <a href="/relative">y</a> <a name="z">w</a> [m](ftp://h.example/f)')
        self.assertEqual(text, "x y w m")
        self.assertEqual(refs, [])

    def test_translator_and_extension_debris_is_removed(self) -> None:
        self.assertEqual(
            html_to_text('released. <div id="gtx-trans" style="position: absolute; left: 106px;"> <div class="gtx-trans-icon">')[0],
            "released.",
        )
        self.assertEqual(
            html_to_text('a <div id="gtx-trans"><div class="gtx-trans-icon"></div> text</div> b')[0],
            "a b",
        )
        self.assertEqual(
            html_to_text('quarantine. <img id="hola-icon-globe" src="safari-extension://C7/f.png" style="top: -11px;" />')[0],
            "quarantine.",
        )

    def test_hr_and_closing_list_make_a_paragraph_break(self) -> None:
        self.assertEqual(
            html_to_text("landers. </ul> <hr /> What was the impact")[0], "landers.\n\nWhat was the impact"
        )

    def test_markdown(self) -> None:
        text, refs = html_to_text("> Who you gonna call? (Bugbusters!)\n\nThe **confinement** due to the __pandemic__")
        self.assertEqual(text, "Who you gonna call? (Bugbusters!)\n\nThe confinement due to the pandemic")
        self.assertEqual(refs, [])
        text, refs = html_to_text(
            "[DW made a video report for its “Focus On Europe” programme](https://www.youtube.com/watch?v=k6RuDhWaWso)"
        )
        self.assertEqual(text, "DW made a video report for its “Focus On Europe” programme")
        self.assertEqual(
            refs,
            [{"url": "https://www.youtube.com/watch?v=k6RuDhWaWso", "label": "DW made a video report for its “Focus On Europe” programme"}],
        )

    def test_markdown_edge_cases(self) -> None:
        self.assertEqual(html_to_text("a * b _ c ** d")[0], "a * b _ c ** d")
        self.assertEqual(html_to_text("**Project team: **Anna")[0], "Project team: Anna")
        self.assertEqual(html_to_text("one\n> two")[0], "one\n\ntwo")
        self.assertEqual(html_to_text("a > b")[0], "a > b")
        self.assertEqual(html_to_text("x https://a.example/p?__tn__=%2C&b=1 y")[0], "x https://a.example/p?__tn__=%2C&b=1 y")
        text, refs = html_to_text("[Wiki](https://en.wikipedia.org/wiki/Foo_(bar)) and ![img](https://a.example/i.png)")
        self.assertEqual(text, "Wiki and ![img](https://a.example/i.png)")
        self.assertEqual(refs, [{"url": "https://en.wikipedia.org/wiki/Foo_(bar)", "label": "Wiki"}])

    def test_other_angle_brackets_are_kept(self) -> None:
        for text in ("<Роскомнадзор> blocked it", "Valeeva< Kristina", "a <bc and c> d", "<href=\"https://a.example/\">x", "1 < 2 > 0"):
            self.assertEqual(html_to_text(text)[0], text)
        self.assertEqual(find_tag_like('<href="x"> <Name> <b>'), ['<href="x">', "<Name>"])

    def test_whitespace_and_paragraphs(self) -> None:
        self.assertEqual(html_to_text("  a \t b  \r\n\r\n\n c\rd \u00a0 e ")[0], "a b\n\nc\n\nd e")
        self.assertEqual(html_to_text("<p> </p><br/> ")[0], "")

    def test_case_insensitive_and_known_names_only(self) -> None:
        self.assertEqual(html_to_text("<B>x</B> <P>y</P> <Sup>z</Sup>")[0], "x\n\ny\n\nz")
        self.assertEqual(html_to_text("<font>x</font> <center>y</center>")[0], "<font>x</font> <center>y</center>")
        self.assertEqual(
            sorted(KNOWN_TAGS),
            sorted("a abbr b blockquote br code div em h1 h2 h3 h4 h5 h6 hr i img li ol p pre s small span strong sub sup table tbody td th thead tr u ul".split()),
        )

    def test_cleaning_twice_changes_nothing(self) -> None:
        for text in ("**********", "a ****b**** c", "<<b>b>", "__a__ __b__", "[[x]](y)", "<a href='https://x.example/'>l<a href='https://y.example/'>"):
            once = html_to_text(text)[0]
            self.assertEqual(html_to_text(once)[0], once, text)

    def test_symbol_only_paragraphs_and_headings(self) -> None:
        self.assertEqual(html_to_text("**\n\n# **\n\n---\n\n= · •\n\nreal")[0], "real")
        self.assertEqual(html_to_text("## Title here\n# **Bold head")[0], "Title here\n\nBold head")
        self.assertEqual(html_to_text("#WildEye is # of people")[0], "#WildEye is # of people")
        self.assertEqual(html_to_text("**Opening only\nclosing only**")[0], "Opening only\n\nclosing only")
        self.assertEqual(html_to_text("a **b** c **")[0], "a b c")

    def test_broken_schemes_are_repaired_in_refs(self) -> None:
        cases = {
            "https://https://a.example/x": "https://a.example/x",
            "https://http://b.example/": "http://b.example/",
            "httphttps://c.example/q": "https://c.example/q",
            "https://d.example/p-35bs://": "https://d.example/p-35b",
            "https://e.example/award/s://": "https://e.example/award/",
        }
        for raw, want in cases.items():
            self.assertEqual(html_to_text(f'<a href="{raw}">l</a>')[1], [{"url": want, "label": "l"}], raw)
            self.assertEqual(html_to_text(f"[l]({raw})")[1], [{"url": want, "label": "l"}], raw)
        for raw in ("adrianblancoramos.com/", "#_msoanchor_1", "https://", "mailto:a@b.example"):
            self.assertEqual(html_to_text(f'<a href="{raw}">l</a>')[1], [], raw)

    def test_ref_url_trailing_punctuation(self) -> None:
        self.assertEqual(html_to_text('<a href="https://a.example/oldu/,">l</a>')[1][0]["url"], "https://a.example/oldu/")
        self.assertEqual(html_to_text('<a href="https://a.example/x;">l</a>')[1][0]["url"], "https://a.example/x")
        self.assertEqual(html_to_text('<a href="https://a.example/#:~:text=a,b,">l</a>')[1][0]["url"], "https://a.example/#:~:text=a,b,")
        self.assertEqual(html_to_text('<a href="https://a.example/x,">https://a.example/x,</a>')[1], [{"url": "https://a.example/x", "label": ""}])

    def test_merge_refs(self) -> None:
        merged = merge_refs(
            [
                [{"url": "https://a.example/", "label": ""}, {"url": "https://b.example/", "label": "B"}],
                [{"url": "https://a.example/", "label": "A"}, {"url": "https://b.example/", "label": "other"}],
            ]
        )
        self.assertEqual(merged, [{"url": "https://a.example/", "label": "A"}, {"url": "https://b.example/", "label": "B"}])


class LinkNotesTest(unittest.TestCase):
    def test_note_follows_the_url_before_it(self) -> None:
        notes = collect_link_notes(
            [
                "https://kqed.zoom.us/rec/play/x?continueMode=true Passcode: ^6@V#ytf",
                "https://vimeo.com/388880381 (password: Australiatalks) [Australia Talks live show]",
                "https://a.example/ plain",
            ]
        )
        self.assertEqual(
            notes,
            {
                "https://kqed.zoom.us/rec/play/x?continueMode=true": "Passcode: ^6@V#ytf",
                "https://vimeo.com/388880381": "(password: Australiatalks) [Australia Talks live show]",
                "https://a.example/": "plain",
            },
        )

    def test_symbol_only_notes_are_dropped(self) -> None:
        self.assertEqual(collect_link_notes(["https://a.example/ ·", "https://b.example/ - (x)", "https://c.example/ — •"]),
                         {"https://b.example/": "- (x)"})

    def test_text_before_the_first_url_and_plain_cells_have_no_note(self) -> None:
        self.assertEqual(collect_link_notes(["Link: https://a.example/x", "https://b.example/"]), {})

    def test_notes_of_one_url_are_joined(self) -> None:
        self.assertEqual(
            collect_link_notes(["https://a.example/ one", "https://a.example/ two"]), {"https://a.example/": "one two"}
        )


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


class RowTextTest(unittest.TestCase):
    """read_rows feeds the ID fingerprint, so it must hand over the CSV text untouched."""

    def test_read_rows_keeps_markup_and_line_breaks(self) -> None:
        build = load_build_module()
        raw = 'Project title,A short description of the project\n"T","> Quote\n\nThe **bold** <a href=""https://a.example/"">x</a>"\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.csv"
            path.write_text(raw, encoding="utf-8")
            row = build.read_rows(path)[0]
        self.assertEqual(row["A short description of the project"], '> Quote\n\nThe **bold** <a href="https://a.example/">x</a>')
        text, refs = build.first_text(row["A short description of the project"])
        self.assertEqual(text, "Quote\n\nThe bold x")
        self.assertEqual(refs, [{"url": "https://a.example/", "label": "x"}])
        self.assertEqual(build.compact_summary(text), "Quote The bold x")

    def test_translation_survives_cleaning_and_paragraphs(self) -> None:
        build = load_build_module()
        old_source = 'Intro <a href="https://a.example/">link</a><ul> <li>one</li> </ul> > quote'
        new_source, _ = build.first_text("Intro <a href=\"https://a.example/\">link</a>\n<ul>\n<li>one</li>\n</ul>\n> quote")
        target = {"summary": new_source}
        stats: dict = {}
        build.carry_ja(target, {"summaryJa": "前置き <b>リンク</b>\n\n- 一"}, old_source, "summaryJa", "summary", "details", stats)
        self.assertEqual(target["summaryJa"], "前置き リンク\n\n- 一")
        self.assertEqual(stats["details.summaryJa"]["kept"], 1)
        target = {"summary": new_source + " changed"}
        build.carry_ja(target, {"summaryJa": "x"}, old_source, "summaryJa", "summary", "details", stats)
        self.assertNotIn("summaryJa", target)
        self.assertEqual(stats["details.summaryJa"]["source-changed"], 1)


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

    TEXT_FIELDS = ("summary", "impact", "jury", "tools", "authors")

    def text_values(self):
        for entry_id, record in self.details.items():
            for field in self.TEXT_FIELDS + tuple(f"{name}Ja" for name in self.TEXT_FIELDS):
                if record.get(field):
                    yield entry_id, field, record[field]

    def test_known_text_examples(self) -> None:
        d = self.details
        summary_0091 = d["2020-s-0091"]["summary"]
        self.assertTrue(summary_0091.startswith("#WildEye is a pioneering"))
        self.assertEqual(
            d["2020-s-0091"]["refs"][0], {"url": "https://oxpeckers.org/wildeyemap/", "label": "#WildEye"}
        )
        self.assertIn("non-dairy, etc.), and countries", d["2021-s-0380"]["summary"])
        self.assertIn("69th place", d["2020-s-0089"]["impact"])
        impact_0130 = d["2020-s-0130"]["impact"]
        self.assertRegex(impact_0130, r"emissions\.\n\nDallas\n\nhttps://www\.dallasnews\.com/\S+ https://www\.dmagazine\.com/\S+")
        ref_urls = [ref["url"] for ref in d["2020-s-0130"]["refs"]]
        self.assertIn("https://www.dmagazine.com/frontburner/2019/10/new-map-of-auto-emissions-in-america-shows-dallas-is-outpacing-its-peers/", ref_urls)
        impact_0005 = d["2021-s-0005"]["impact"]
        self.assertRegex(impact_0005, r"\(https://www1\.folha\.uol\.com\.br/\S+shtml ?\)\.")
        folha = [ref for ref in d["2021-s-0005"]["refs"] if ref["url"].startswith("https://www1.folha.uol.com.br/")]
        self.assertTrue(folha and all(ref["label"] == "" for ref in folha))
        self.assertIn("district and subdistrict level ),", d["2021-s-0024"]["summary"])
        self.assertTrue(any("web.archive.org" in ref["url"] and "selangor" in ref["url"] for ref in d["2021-s-0024"]["refs"]))
        summary_0392 = d["2023-s-0392"]["summary"]
        self.assertTrue(summary_0392.startswith("Who you gonna call? (Bugbusters!)\n\nThe confinement due to"))
        self.assertNotIn("**", summary_0392)
        label = "DW made a video report for its “Focus On Europe” programme"
        self.assertIn({"url": "https://www.youtube.com/watch?v=k6RuDhWaWso", "label": label}, d["2023-s-0023"]["refs"])
        self.assertIn(label, d["2023-s-0023"]["impact"])
        self.assertNotIn("](", d["2023-s-0023"]["impact"])
        self.assertTrue(d["2020-s-0162"]["impact"].endswith("results released."))
        self.assertTrue(d["2021-s-0423"]["summary"].endswith("quarantine."))
        self.assertIn("landers.\n\nWhat was the impact", d["2020-s-0246"]["impact"])
        self.assertIn("<Роскомнадзор>", d["2023-f-0082"]["summary"])
        self.assertTrue(any("Valeeva< Kristina" in text for i, _, text in self.text_values() if i == "2021-s-0401"))

    def test_known_cleanup_examples(self) -> None:
        d = self.details
        for entry_id, field in (("2023-f-0043", "summary"), ("2023-s-0335", "authors"), ("2023-f-0050", "summary"), ("2023-s-0013", "summary")):
            text = d[entry_id][field]
            self.assertTrue(text and not text.startswith(("#", "*", "-")), entry_id)
            self.assertNotIn("\n\n**", text, entry_id)
            self.assertNotRegex(text, r"(?:^|\n\n)[*#\-=_·•\s]*(?:\n\n|$)", entry_id)
        self.assertEqual(d["2023-s-0335"]["authors"].split("\n\n")[0].split(" ")[:2], ["Reem", "Allam"])
        for entry_id in ("2024-s-0095", "2023-f-0050", "2023-s-0155", "2023-s-0109"):
            urls = [ref["url"] for ref in d[entry_id]["refs"]]
            self.assertTrue(urls, entry_id)
            for url in urls:
                self.assertNotRegex(url, r"(?i)https?:/?/?https?|http(?!s?://)|s://$", f"{entry_id} {url}")
        self.assertIn("http://kenyalaw.org/kl/", [ref["url"] for ref in d["2023-s-0155"]["refs"]])
        self.assertTrue(any(ref["url"].startswith("https://www.dataphyte.com/") for ref in d["2023-s-0109"]["refs"]))
        for ref in d["2020-f-0009"]["refs"]:
            self.assertNotRegex(ref["url"], r"[,;]$")
        self.assertIn("https://medyascope.tv/2019/08/22/sadece-son-bir-ayda-200-orman-yangini-cikti/", [r["url"] for r in d["2020-f-0009"]["refs"]])
        self.assertNotIn("linkNotes", d["2022-s-0210"])

    def test_known_link_notes(self) -> None:
        zoom = self.details["2022-s-0269"]["linkNotes"]
        self.assertEqual(list(zoom.values()), ["Passcode: ^6@V#ytf"])
        self.assertIn(next(iter(zoom)), self.details["2022-s-0269"]["links"])
        vimeo = self.details["2020-s-0168"]["linkNotes"]["https://vimeo.com/388880381"]
        self.assertTrue(vimeo.startswith("(password: Australiatalks)"))

    def test_text_has_no_markup(self) -> None:
        tag = re.compile(r"</?(?:%s)(?=[\s/>])[^<>]*>" % "|".join(sorted(KNOWN_TAGS, key=len, reverse=True)), re.I)
        pair_bold = re.compile(r"(?<!\*)\*\*[^\s*].*?[^*]\*\*(?!\*)")
        for entry_id, field, text in self.text_values():
            where = f"{entry_id} {field}"
            self.assertIsNone(tag.search(text), where)
            self.assertNotIn("<!--", text, where)
            self.assertIsNone(pair_bold.search(text), where)
            self.assertIsNone(re.search(r"(?:^|\n\n)>\s", text), where)
            for paragraph in text.split("\n\n"):
                self.assertTrue(paragraph and paragraph == re.sub(r"\s+", " ", paragraph).strip(), where)
                self.assertFalse(re.fullmatch(r"[\s*_#\-=·•]*", paragraph), f"{where}: {paragraph[:40]}")

    def test_text_is_stable_under_cleaning(self) -> None:
        for entry_id, field, text in self.text_values():
            self.assertEqual(html_to_text(text)[0], text, f"{entry_id} {field}")

    def test_entry_summary_is_one_compact_line(self) -> None:
        for entry in self.entries:
            summary = entry["summary"]
            self.assertNotRegex(summary, r"\s{2}|\n", entry["id"])
            self.assertLessEqual(len(summary), 240, entry["id"])
            full = re.sub(r"\s+", " ", self.details[entry["id"]]["summary"])
            self.assertTrue(full.startswith(summary.rstrip("…")), entry["id"])
            if entry.get("summaryJa"):
                self.assertNotRegex(entry["summaryJa"], r"\s{2}|\n", entry["id"])

    def test_refs_and_link_notes(self) -> None:
        fixes: dict[str, list[str]] = {}
        for fix in json.loads((DATA_DIR / "url-fixes.json").read_text(encoding="utf-8"))["fixes"]:
            fixes.setdefault(fix["id"], []).extend(fix["dropped"])
        with_refs = with_notes = 0
        for entry_id, record in self.details.items():
            refs = record.get("refs")
            if "refs" in record:
                with_refs += 1
                self.assertTrue(refs, entry_id)
                urls = [ref["url"] for ref in refs]
                self.assertEqual(len(urls), len(set(urls)), entry_id)
                for ref in refs:
                    self.assertEqual(set(ref), {"url", "label"}, entry_id)
                    self.assertTrue(is_valid_url(ref["url"]), f"{entry_id}: {ref['url'][:100]}")
                    self.assertNotRegex(ref["url"], r"[,;]$|(?i:https?:/?/?https?)", f"{entry_id}: {ref['url'][:100]}")
                    self.assertNotEqual(ref["label"].rstrip("/"), ref["url"].rstrip("/") if ref["label"] else None, entry_id)
                    self.assertEqual(ref["label"], ref["label"].strip(), entry_id)
                    self.assertNotRegex(ref["label"], r"\s{2}|\n", entry_id)
            notes = record.get("linkNotes")
            if "linkNotes" in record:
                with_notes += 1
                self.assertTrue(notes, entry_id)
                for url, note in notes.items():
                    self.assertIn(url, record["links"], entry_id)
                    self.assertTrue(note.strip(), entry_id)
                    self.assertRegex(note, r"\w", entry_id)
                    for part in note.split(" "):
                        self.assertTrue(any(part in dropped for dropped in fixes.get(entry_id, [])), f"{entry_id}: {part}")
        self.assertGreater(with_refs, 200)
        self.assertGreater(with_notes, 10)

    def test_ids_are_unchanged(self) -> None:
        ledger = json.loads((DATA_DIR.parents[1] / "scripts" / "sigma" / "ids.json").read_text(encoding="utf-8"))
        live = {key for key, row in ledger["entries"].items() if not row.get("removed")}
        self.assertEqual({entry["id"] for entry in self.entries}, live)
        import subprocess

        shown = subprocess.run(
            ["git", "-C", str(DATA_DIR.parents[1]), "show", "main:public/data/entries.json"],
            capture_output=True, text=True,
        )
        if shown.returncode == 0:
            main_ids = {entry["id"] for entry in json.loads(shown.stdout)["entries"]}
            self.assertEqual({entry["id"] for entry in self.entries}, main_ids)

    def test_url_fixes_log(self) -> None:
        log = json.loads((DATA_DIR / "url-fixes.json").read_text(encoding="utf-8"))
        self.assertEqual(log["count"], len(log["fixes"]))
        for fix in log["fixes"]:
            self.assertEqual(set(fix), {"id", "field", "original", "result", "dropped"})
            self.assertIn(fix["id"], self.details)


if __name__ == "__main__":
    unittest.main()
