"""Tests for <unk> handling in translate-ja.py. No model or transformers needed."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("translate_ja", ROOT / "scripts/translate-ja.py")
tj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tj)

UNK = "<unk>"
VOCAB_BAD = set("₂ł")


class FakeTokenizer:
    unk_token_id = 3
    src_lang = "eng_Latn"

    def encode(self, text):
        return [self.unk_token_id if ch in VOCAB_BAD else 10 for ch in text]


class FakeEngine:
    """Returns scripted outputs per call: a list of dicts text -> output."""

    def __init__(self, greedy=None, beam=None):
        self.tokenizer = FakeTokenizer()
        self.greedy = greedy or {}
        self.beam = beam or {}
        self.calls = []

    def translate_many(self, items, beam_size=1, num_hypotheses=1):
        self.calls.append((beam_size, [t for _l, t in items]))
        table = self.greedy if beam_size == 1 else self.beam
        return [table.get(t, "訳:" + t) for _l, t in items]


class NormalizeTests(unittest.TestCase):
    def test_rules(self):
        n = tj.normalize_source
        self.assertEqual(n("„a“ ”b” «c» »d«"), '"a" "b" "c" "d"')
        self.assertEqual(n("Officials’ ‘x’ ‚y‚"), "Officials' 'x' 'y'")
        self.assertEqual(n("a–b—c"), "a-b-c")
        self.assertEqual(n("wait…"), "wait...")
        self.assertEqual(n("a b"), "a b")
        self.assertEqual(n("a​b‌‍⁠﻿c"), "abc")
        self.assertEqual(n("₦500"), "NGN 500")
        self.assertEqual(n("₦ 500"), "NGN 500")

    def test_plain_text_unchanged(self):
        self.assertEqual(tj.normalize_source("Plain 日本語 text."), "Plain 日本語 text.")

    def test_cache_key_uses_original_text(self):
        jobs = tj.collect_jobs(
            [{"id": "a", "year": 2020, "title": "„Hi“", "langs": ""}], {2020: {}}
        )
        self.assertEqual(jobs[0][0], tj.cache_key("eng_Latn", "„Hi“"))
        self.assertEqual(jobs[0][2], "„Hi“")


class UnkInputTests(unittest.TestCase):
    def test_find_unk_chars(self):
        tok = FakeTokenizer()
        self.assertEqual(tj.find_unk_chars(tok, "eng_Latn", "ok text"), [])
        self.assertEqual(tj.find_unk_chars(tok, "eng_Latn", "a₂ b₂ ł"), ["₂", "ł"])

    def test_audit_output(self):
        lines = []
        bad = tj.audit_vocab(
            [("eng_Latn", "x₂ ł₂ ₂"), ("eng_Latn", "„q“ plain")], FakeTokenizer(), out=lines.append
        )
        self.assertEqual(bad, [("₂", 3), ("ł", 1)])
        self.assertEqual(lines[1:], ["U+2082\t₂\t3", "U+0142\tł\t1"])


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log = self.logs.append

    def resolve(self, engine, **kw):
        return tj.resolve_pieces(engine, [("eng_Latn", "src")], log=self.log, **kw)

    def test_clean_output_no_retry(self):
        engine = FakeEngine()
        self.assertEqual(self.resolve(engine), ["訳:src"])
        self.assertEqual([c[0] for c in engine.calls], [1])

    def test_beam_retry_fixes(self):
        engine = FakeEngine(greedy={"src": "灌" + UNK}, beam={"src": "灌漑"})
        self.assertEqual(self.resolve(engine), ["灌漑"])
        self.assertEqual([c[0] for c in engine.calls], [1, tj.RETRY_BEAM])

    def test_order_beam_ollama_corrections(self):
        order = []
        engine = FakeEngine(greedy={"src": "深" + UNK}, beam={"src": "深" + UNK})

        def ollama(text):
            order.append("ollama")
            return "深" + UNK

        out = self.resolve(engine, ollama=ollama, corrections={"深<unk>": "深圳"})
        self.assertEqual([c[0] for c in engine.calls], [1, tj.RETRY_BEAM])
        self.assertEqual(order, ["ollama"])
        self.assertEqual(out, ["深圳"])  # dictionary is the third stage

    def test_ollama_result_used(self):
        engine = FakeEngine(greedy={"src": UNK}, beam={"src": UNK})
        self.assertEqual(self.resolve(engine, ollama=lambda t: "オラマ"), ["オラマ"])

    def test_ollama_error_falls_through(self):
        engine = FakeEngine(greedy={"src": "棕" + UNK}, beam={"src": "棕" + UNK})

        def boom(text):
            raise OSError("down")

        out = self.resolve(engine, ollama=boom, corrections={"棕<unk>": "棕櫚"})
        self.assertEqual(out, ["棕櫚"])

    def test_corrections_tolerate_spacing(self):
        self.assertEqual(
            tj.apply_corrections("灌 <unk> 水と瓦<unk>", {"灌<unk>": "灌漑", "瓦<unk>": "瓦礫"}),
            "灌漑水と瓦礫",
        )

    def test_unresolved_is_empty(self):
        engine = FakeEngine(greedy={"src": "a" + UNK}, beam={"src": "a" + UNK})
        self.assertEqual(self.resolve(engine, corrections={"x<unk>": "y"}), [""])

    def test_shipped_corrections_file(self):
        corr = tj.load_corrections()
        for broken, fixed in {"灌<unk>": "灌漑", "棕<unk>": "棕櫚", "深<unk>": "深圳", "瓦<unk>": "瓦礫", "弾<unk>": "弾劾"}.items():
            self.assertEqual(corr[broken], fixed)


class BatchTests(unittest.TestCase):
    def test_unk_not_cached_and_marked_failed(self):
        engine = FakeEngine(greedy={"bad": "x" + UNK}, beam={"bad": "x" + UNK})
        items = [("k1", "eng_Latn", "good"), ("k2", "eng_Latn", "bad")]
        cache, failed = {}, {}
        tj.translate_job_batch(engine, items, cache, failed, log=lambda m: None)
        self.assertEqual(cache, {"k1": "訳:good"})
        self.assertEqual(list(failed), ["k2"])
        self.assertFalse(any(UNK in v for v in cache.values()))

    def test_normalized_text_sent_but_original_keyed(self):
        engine = FakeEngine()
        cache, failed = {}, {}
        tj.translate_job_batch(engine, [("k", "eng_Latn", "„a“")], cache, failed, log=lambda m: None)
        self.assertEqual(engine.calls[0][1], ['"a"'])
        self.assertIn("k", cache)

    def test_input_unk_logged(self):
        logs = []
        tj.translate_job_batch(
            FakeEngine(), [("kkkkkkkk", "eng_Latn", "a₂")], {}, {}, log=logs.append
        )
        self.assertTrue(any("U+2082" in m for m in logs))

    def test_pending_skips_done_unk_and_failed(self):
        jobs = [("a", "l", "t"), ("b", "l", "t"), ("c", "l", "t"), ("d", "l", "t")]
        cache = {"a": "ok", "b": "x" + UNK}
        self.assertEqual([j[0] for j in tj.pending_jobs(jobs, cache, {"c": ""})], ["b", "d"])


class DataTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.data = self.dir / "data"
        self.data.mkdir()
        self.cache = self.dir / "ja-cache.json"
        self.title_cache = self.dir / "ja-title-cache.json"
        self.failed = self.dir / "ja-failed.json"
        self.patches = [
            patch.object(tj, "DATA", self.data),
            patch.object(tj, "CACHE_PATH", self.cache),
            patch.object(tj, "TITLE_CACHE_PATH", self.title_cache),
            patch.object(tj, "FAILED_PATH", self.failed),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def run_main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tj.main(list(argv))
        return buf.getvalue()


class PurgeTests(DataTmp):
    def test_purge_removes_only_unk(self):
        self.write(self.cache, {"a": "良い", "b": "灌" + UNK, "c": UNK})
        self.write(self.title_cache, {"t1": "題", "t2": "深" + UNK})
        self.write(
            self.data / "entries.json",
            {
                "years": [2021],
                "entries": [
                    {"id": "1", "title": "T", "titleJa": "深" + UNK, "summaryJa": "良い"},
                    {"id": "2", "title": "U", "titleJa": "良い", "summaryJa": "瓦" + UNK},
                ],
            },
        )
        self.write(
            self.data / "details-2021.json",
            {
                "1": {"summary": "s", "summaryJa": "良い", "impactJa": "弾" + UNK, "juryJa": "良い"},
                "2": {"summaryJa": UNK, "impactJa": "良い"},
            },
        )
        out = self.run_main("--purge-unk")
        self.assertEqual(self.read(self.cache), {"a": "良い"})
        self.assertEqual(self.read(self.title_cache), {"t1": "題"})
        entries = self.read(self.data / "entries.json")["entries"]
        self.assertEqual(entries[0], {"id": "1", "title": "T", "summaryJa": "良い"})
        self.assertEqual(entries[1], {"id": "2", "title": "U", "titleJa": "良い"})
        details = self.read(self.data / "details-2021.json")
        self.assertEqual(details["1"], {"summary": "s", "summaryJa": "良い", "juryJa": "良い"})
        self.assertEqual(details["2"], {"impactJa": "良い"})
        self.assertIn("purged titleJa 1", out)
        self.assertIn("purged summaryJa 2", out)
        self.assertIn("purged impactJa 1", out)
        self.assertIn("purged cache 2", out)
        self.assertIn("purged total", out)

    def test_clean_files_not_rewritten(self):
        path = self.data / "entries.json"
        path.write_text('{ "entries": [ {"titleJa": "x"} ] }', encoding="utf-8")
        self.run_main("--purge-unk")
        self.assertEqual(path.read_text(encoding="utf-8"), '{ "entries": [ {"titleJa": "x"} ] }')


class AuditMainTests(DataTmp):
    def test_audit_vocab_prints_and_does_not_translate(self):
        self.write(
            self.data / "entries.json",
            {"years": [2020], "entries": [{"id": "1", "year": 2020, "title": "Hello ₂ ł₂", "langs": ""}]},
        )
        self.write(self.data / "details-2020.json", {"1": {"summary": "plain ł"}})
        with patch.object(tj, "load_tokenizer", FakeTokenizer), patch.object(
            tj, "Nllb", side_effect=AssertionError("must not translate")
        ):
            out = self.run_main("--audit-vocab")
        self.assertIn("U+2082\t₂\t2", out)
        self.assertIn("U+0142\tł\t2", out)
        self.assertFalse(self.cache.exists())


class WriteBackTests(DataTmp):
    def test_empty_translation_drops_existing_ja(self):
        self.write(
            self.data / "entries.json",
            {"years": [2020], "entries": [{"id": "1", "year": 2020, "titleJa": "x", "summaryJa": "y"}]},
        )
        self.write(self.data / "details-2020.json", {"1": {"summaryJa": "y", "impactJa": "z"}})
        entries = [{"id": "1", "year": 2020, "titleJa": "", "summaryJa": "y"}]
        tj.patch_into_files(entries, {2020: {"1": {"summaryJa": "", "impactJa": "z"}}})
        self.assertEqual(self.read(self.data / "entries.json")["entries"][0], {"id": "1", "year": 2020, "summaryJa": "y"})
        self.assertEqual(self.read(self.data / "details-2020.json")["1"], {"impactJa": "z"})

    def test_apply_does_not_write_cached_unk(self):
        entry = {"id": "1", "year": 2020, "title": "Hello", "langs": "", "titleJa": "古" + UNK}
        cache = {tj.cache_key("eng_Latn", "Hello"): "深" + UNK}
        tj.apply_translations(cache, {}, [entry], {2020: {}})
        self.assertEqual(entry["titleJa"], "")


if __name__ == "__main__":
    unittest.main()
