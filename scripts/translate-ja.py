#!/usr/bin/env python3
"""Translate catalog titles and long fields into Japanese with local NLLB."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
MODEL_DIR = ROOT / ".tmp-data" / "nllb-ct2"
TOKENIZER_DIR = ROOT / ".tmp-data" / "nllb-tok"
CACHE_PATH = ROOT / ".tmp-data" / "ja-cache.json"
FAILED_PATH = ROOT / ".tmp-data" / "ja-failed.json"
CORRECTIONS_PATH = ROOT / "scripts" / "ja-unk-corrections.json"
UNK = "<unk>"
RETRY_BEAM = 5
OLLAMA_MIN_JA_RATIO = 0.3

JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
SENT_SPLIT = re.compile(r"(?<=[.!?。！？…])\s+")
SUMMARY_JA_LIMIT = 120

HINTS: list[tuple[tuple[str, ...], str]] = [
    (("portugu", "português", "brazilian portuguese", "pt-br", "pt_br"), "por_Latn"),
    (("español", "espanol", "spanish", "castellano"), "spa_Latn"),
    (("français", "francais", "french"), "fra_Latn"),
    (("deutsch", "german"), "deu_Latn"),
    (("italiano", "italian"), "ita_Latn"),
    (("nederlands", "dutch"), "nld_Latn"),
    (("україн", "ukrainian"), "ukr_Cyrl"),
    (("русск", "russian"), "rus_Cyrl"),
    (("العرب", "arabic"), "arb_Arab"),
    (("中文", "chinese", "mandarin"), "zho_Hans"),
    (("한국어", "korean"), "kor_Hang"),
    (("日本語", "japanese"), "jpn_Jpan"),
    (("polski", "polish"), "pol_Latn"),
    (("türk", "turkish"), "tur_Latn"),
    (("ελλην", "greek"), "ell_Grek"),
    (("suomi", "finnish"), "fin_Latn"),
    (("norsk", "norwegian"), "nob_Latn"),
    (("svensk", "swedish"), "swe_Latn"),
    (("čeština", "czech"), "ces_Latn"),
    (("magyar", "hungarian"), "hun_Latn"),
    (("română", "romanian"), "ron_Latn"),
    (("bahasa indonesia", "indonesian"), "ind_Latn"),
    (("हिन्दी", "hindi"), "hin_Deva"),
    (("தமிழ்", "tamil"), "tam_Taml"),
    (("ไทย", "thai"), "tha_Thai"),
    (("english", "inglês", "ingles"), "eng_Latn"),
]


def is_japanese(text: str) -> bool:
    if not text:
        return False
    hits = len(JP_RE.findall(text))
    return hits >= 8 or hits / max(len(text), 1) >= 0.3


def detect_lang(text: str, hint: str = "") -> str:
    if is_japanese(text):
        return "jpn_Jpan"
    if re.search(r"[\u0600-\u06ff]", text):
        return "arb_Arab"
    if re.search(r"[\u0400-\u04ff]", text):
        return "ukr_Cyrl" if re.search(r"[іїєґІЇЄҐ]", text) else "rus_Cyrl"
    if re.search(r"[\uac00-\ud7af]", text):
        return "kor_Hang"
    if re.search(r"[\u3040-\u30ff]", text):
        return "jpn_Jpan"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zho_Hans"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "tha_Thai"
    if re.search(r"[\u0900-\u097f]", text):
        return "hin_Deva"
    if re.search(r"[\u0b80-\u0bff]", text):
        return "tam_Taml"
    blob = f"{hint}\n{text[:400]}".lower()
    for keys, code in HINTS:
        if any(key in blob for key in keys):
            return code
    return "eng_Latn"


_PUNCT_MAP = {
    **dict.fromkeys("\u201e\u201c\u201d\u00ab\u00bb", '"'),
    **dict.fromkeys("\u2018\u2019\u201a", "'"),
    **dict.fromkeys("\u2010\u2011\u2012\u2013\u2015\u2212", "-"),
    "\u2014": " - ",
    "\u2026": "...",
    "\u00a0": " ",
    "\u20a6": "NGN ",
    # ZWNJ/ZWJ (U+200C/200D) are kept: they join or split letters in Persian, Hindi, etc.
    **dict.fromkeys("\u200b\u200e\u200f\u2060\u2066\u2067\u2068\u2069\ufeff", None),
}
_PUNCT_RE = re.compile("[" + "".join(_PUNCT_MAP) + "]")


def normalize_source(text: str) -> str:
    """Moses replace-unicode-punctuation style cleanup of NLLB input.

    Used only for text sent to the translation model. The source JSON is never
    rewritten, and cache keys are computed from the *original* text (see
    cache_key callers), so existing caches stay valid and the same original
    always maps to the same entry regardless of how normalization evolves.
    """
    text = _PUNCT_RE.sub(lambda m: _PUNCT_MAP[m.group(0)] or "", text)
    return re.sub(r" {2,}", " ", text)


def find_unk_chars(tokenizer, lang: str, text: str) -> list[str]:
    """Characters of `text` that the tokenizer maps to its unknown token."""
    unk_id = tokenizer.unk_token_id
    tokenizer.src_lang = lang
    if unk_id not in tokenizer.encode(text):
        return []
    return [
        char
        for char in dict.fromkeys(text)
        if not char.isspace() and unk_id in tokenizer.encode(char)
    ]


def format_chars(chars) -> str:
    return " ".join(f"U+{ord(char):04X}{char!r}" for char in chars)


def audit_vocab(items, tokenizer, out=print) -> list[tuple[str, int]]:
    """List out-of-vocabulary characters (after normalization) with counts."""
    counts: Counter[str] = Counter()
    for _lang, text in items:
        counts.update(char for char in normalize_source(text) if not char.isspace())
    unk_id = tokenizer.unk_token_id
    bad = [(char, n) for char, n in counts.items() if unk_id in tokenizer.encode(char)]
    bad.sort(key=lambda row: (-row[1], row[0]))
    out(f"audit chars {len(counts)} out-of-vocab {len(bad)}")
    for char, n in bad:
        out(f"U+{ord(char):04X}\t{char}\t{n}")
    return bad


def load_corrections(path: Path | None = None) -> dict[str, str]:
    path = CORRECTIONS_PATH if path is None else path
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k and isinstance(v, str)}


def apply_corrections(text: str, corrections: dict[str, str], log=None) -> str:
    text = re.sub(r"\s*" + re.escape(UNK) + r"\s*", UNK, text)
    for broken in sorted(corrections, key=len, reverse=True):
        fixed = corrections[broken]
        if log is not None:
            start = 0
            while (at := text.find(broken, start)) != -1:
                end = at + len(broken)
                log(f"correction {broken!r} -> {fixed!r} in ...{text[max(0, at - 12):end + 12]}...")
                start = end
        text = text.replace(broken, fixed)
    return text


def cleanup_ja(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3040-\u30ff\u4e00-\u9fff])\s+(?=[\u3040-\u30ff\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([、。！？])", r"\1", text)
    return text.strip()


def compact_ja(text: str, limit: int = SUMMARY_JA_LIMIT) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def split_chunks(text: str, max_chars: int = 480) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    pieces = SENT_SPLIT.split(text)
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
        while len(piece) > max_chars:
            chunks.append(piece[:max_chars])
            piece = piece[max_chars:]
        buf = piece
    if buf:
        chunks.append(buf)
    return chunks


def cache_key(lang: str, text: str) -> str:
    return hashlib.sha1(f"{lang}\n{text}".encode()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def set_or_drop(target: dict, key: str, source: dict, source_key: str) -> None:
    """Write a non-empty translation; an empty one removes the existing value."""
    if source.get(source_key):
        target[key] = source[source_key]
    elif source_key in source:
        target.pop(key, None)


def patch_into_files(entries: list[dict], details_by_year: dict[int, dict]) -> None:
    payload = load_json(DATA / "entries.json")
    updates = {entry["id"]: entry for entry in entries}
    rows = {row["id"]: row for row in payload["entries"]}
    for row_id, row in rows.items():
        source = updates.get(row_id)
        if not source:
            continue
        for key in ("titleJa", "summaryJa"):
            set_or_drop(row, key, source, key)
    for year, records in details_by_year.items():
        path = DATA / f"details-{year}.json"
        current = load_json(path)
        for entry_id, record in records.items():
            if entry_id not in current:
                continue
            for key in ("summaryJa", "impactJa", "juryJa"):
                set_or_drop(current[entry_id], key, record, key)
            if "summaryJa" in record and not record["summaryJa"] and entry_id in rows:
                rows[entry_id].pop("summaryJa", None)
        dump_json(path, current)
    dump_json(DATA / "entries.json", payload)


def load_tokenizer():
    sys.path.insert(0, str(ROOT / ".venv" / "lib"))
    from transformers import AutoTokenizer

    local = (TOKENIZER_DIR / "tokenizer.json").exists() or (
        TOKENIZER_DIR / "sentencepiece.bpe.model"
    ).exists()
    return AutoTokenizer.from_pretrained(str(TOKENIZER_DIR) if local else "facebook/nllb-200-distilled-600M")


class Nllb:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / ".venv" / "lib"))
        import ctranslate2

        if not (MODEL_DIR / "model.bin").exists():
            raise SystemExit(f"Missing NLLB model at {MODEL_DIR}")
        self.tokenizer = load_tokenizer()
        self.translator = ctranslate2.Translator(
            str(MODEL_DIR),
            device="cpu",
            compute_type="int8",
            inter_threads=4,
            intra_threads=2,
        )

    def translate_many(
        self,
        items: list[tuple[str, str]],
        beam_size: int = 1,
        num_hypotheses: int = 1,
        disable_unk: bool = False,
    ) -> list[str]:
        """items: (src_lang, text) all same src_lang recommended but not required."""
        if not items:
            return []
        by_lang: dict[str, list[int]] = {}
        out = [""] * len(items)
        for index, (lang, text) in enumerate(items):
            by_lang.setdefault(lang, []).append(index)
        for lang, indexes in by_lang.items():
            self.tokenizer.src_lang = lang
            sources = []
            for index in indexes:
                tokens = self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(items[index][1]))
                sources.append(tokens)
            results = self.translator.translate_batch(
                sources,
                target_prefix=[["jpn_Jpan"]] * len(sources),
                beam_size=beam_size,
                num_hypotheses=num_hypotheses,
                disable_unk=disable_unk,
                max_batch_size=32,
                max_decoding_length=256,
            )
            for index, result in zip(indexes, results):
                # Prefer the best hypothesis that has no <unk>; else the top one.
                tokens = next(
                    (hyp for hyp in result.hypotheses if UNK not in hyp), result.hypotheses[0]
                )
                if tokens and tokens[0] == "jpn_Jpan":
                    tokens = tokens[1:]
                out[index] = cleanup_ja(
                    self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(tokens))
                )
        return out


def collect_jobs(
    entries: list[dict],
    details_by_year: dict[int, dict],
    year: int | None = None,
    include_titles: bool = True,
) -> list[tuple[str, str, str]]:
    jobs: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(text: str, hint: str) -> None:
        text = (text or "").strip()
        if not text or is_japanese(text):
            return
        lang = detect_lang(text, hint)
        key = cache_key(lang, text)
        if key in seen:
            return
        seen.add(key)
        jobs.append((key, lang, text))

    for entry in entries:
        if year and entry["year"] != year:
            continue
        hint = entry.get("langs") or ""
        if include_titles:
            add(entry.get("title") or "", hint)
        details = details_by_year.get(entry["year"], {}).get(entry["id"], {})
        add(details.get("summary") or entry.get("summary") or "", hint)
        add(details.get("impact") or "", hint)
        add(details.get("jury") or "", hint)
    return jobs


TITLE_CACHE_PATH = ROOT / ".tmp-data" / "ja-title-cache.json"


OLLAMA_URL = "http://127.0.0.1:11434"


def ollama_available(timeout: float = 2.0) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def ollama_translate(text: str, model: str = "gemma4:e4b", kind: str = "body") -> str:
    import json as json_lib
    import urllib.request

    if kind == "title":
        prompt = (
            "次の作品タイトルを自然な日本語に翻訳してください。"
            "固有名詞はカタカナや現地の通称を使い、訳文だけを1行で出力してください。"
            "説明や引用符は不要です。\n"
            f"{text}"
        )
        limit = 120
    else:
        prompt = (
            "次の文章を自然な日本語に翻訳してください。"
            "固有名詞はカタカナや現地の通称を使い、訳文だけを出力してください。"
            "説明や引用符は不要です。\n"
            f"{text}"
        )
        limit = 1024
    body = json_lib.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "think": False,
            "options": {"temperature": 0, "num_predict": limit},
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json_lib.loads(response.read().decode())
    out = (payload.get("response") or "").strip()
    if kind == "title":
        out = next((row.strip() for row in out.splitlines() if row.strip()), "")
        out = out.strip('「」""\' ')
    return cleanup_ja(out)


def ollama_translate_title(title: str, model: str = "gemma4:e4b") -> str:
    return ollama_translate(title, model, kind="title")


def japanese_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    return len(JP_RE.findall(text)) / len(chars) if chars else 0.0


def acceptable_fallback(text: str) -> bool:
    return bool(text) and UNK not in text and japanese_ratio(text) >= OLLAMA_MIN_JA_RATIO


def resolve_pieces(
    engine,
    pieces: list[tuple[str, str]],
    *,
    retry_beam: int = RETRY_BEAM,
    ollama=None,
    corrections: dict[str, str] | None = None,
    log=print,
) -> list[str | None]:
    """Translate pieces; None marks a piece that still contains <unk>.

    Order: greedy -> wider beam with disable_unk -> Ollama (only if given)
    -> correction dictionary. An empty string is a legitimate empty translation.
    """
    results: list[str | None] = list(engine.translate_many(pieces))
    best_nllb = list(results)
    bad = [i for i, text in enumerate(results) if UNK in text]
    if bad:
        log(f"unk output {len(bad)}/{len(pieces)}: retry beam={retry_beam} disable_unk")
        retried = engine.translate_many(
            [pieces[i] for i in bad],
            beam_size=retry_beam,
            num_hypotheses=retry_beam,
            disable_unk=True,
        )
        for i, text in zip(bad, retried):
            results[i] = best_nllb[i] = text
        bad = [i for i in bad if UNK in results[i]]
    if bad and ollama is not None:
        log(f"unk output {len(bad)}: ollama")
        for i in bad:
            try:
                candidate = ollama(pieces[i][1])
            except Exception as error:
                log(f"ollama fail {error}")
                continue
            if acceptable_fallback(candidate):
                results[i] = candidate
            else:
                log("ollama output rejected (empty, <unk>, or not Japanese)")
        bad = [i for i in bad if UNK in results[i]]
    if bad and corrections:
        for i in bad:
            fixed = apply_corrections(best_nllb[i], corrections, log=log)
            if UNK not in fixed:
                results[i] = fixed
        bad = [i for i in bad if UNK in results[i]]
    for i in bad:
        results[i] = None
    if bad:
        log(f"unk unresolved {len(bad)}")
    return results


def read_json_text(path: Path) -> tuple[object, bool]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw), raw.endswith("\n")


def write_like(path: Path, payload, newline: bool, **dump_kw) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, **dump_kw) + ("\n" if newline else ""), encoding="utf-8")


def purge_unk(data_dir: Path, cache_path: Path, title_cache_path: Path | None = None) -> Counter:
    """Delete <unk>-bearing translations from the caches and data JSON files.

    Files are rewritten only when something was removed, in the same compact
    format and with the same trailing-newline state as before.
    """
    removed: Counter[str] = Counter()

    for path, label in ((cache_path, "cache"), (title_cache_path, "title-cache")):
        if path is None or not path.exists():
            continue
        cache, newline = read_json_text(path)
        kept = {k: v for k, v in cache.items() if not (isinstance(v, str) and UNK in v)}
        if len(kept) != len(cache):
            removed[label] += len(cache) - len(kept)
            write_like(path, kept, newline)

    def walk(node) -> None:
        if isinstance(node, dict):
            for key in list(node):
                value = node[key]
                if key.endswith("Ja") and isinstance(value, str) and UNK in value:
                    del node[key]
                    removed[key] += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    # The card's summaryJa is a truncation of the detail's: drop both together.
    broken_ids: set[str] = set()
    for path in sorted(data_dir.glob("details-*.json")):
        payload, _ = read_json_text(path)
        broken_ids.update(
            entry_id
            for entry_id, record in payload.items()
            if isinstance(record, dict) and UNK in (record.get("summaryJa") or "")
        )

    for path in sorted(data_dir.glob("*.json")):
        payload, newline = read_json_text(path)
        before = sum(removed.values())
        walk(payload)
        if path.name == "entries.json":
            for row in payload.get("entries", []):
                if row.get("id") in broken_ids and "summaryJa" in row:
                    del row["summaryJa"]
                    removed["summaryJa"] += 1
        if sum(removed.values()) != before:
            write_like(path, payload, newline, separators=(",", ":"))
    return removed


def apply_translations(
    cache: dict[str, str],
    title_cache: dict[str, str],
    entries: list[dict],
    details_by_year: dict[int, dict],
) -> None:
    def ja(text: str, hint: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if is_japanese(text):
            return text
        lang = detect_lang(text, hint)
        value = cache.get(cache_key(lang, text), "")
        return "" if UNK in value else value

    def drop_unk(record: dict, key: str) -> None:
        if UNK in (record.get(key) or ""):
            record[key] = ""

    for entry in entries:
        hint = entry.get("langs") or ""
        details = details_by_year.get(entry["year"], {}).get(entry["id"], {})
        title_ja = title_cache.get(entry.get("title") or "") or ja(entry.get("title") or "", hint)
        if UNK in title_ja:
            title_ja = ja(entry.get("title") or "", hint)
        summary_full = details.get("summary") or entry.get("summary") or ""
        summary_ja = ja(summary_full, hint)
        if title_ja:
            entry["titleJa"] = title_ja
        else:
            drop_unk(entry, "titleJa")
        if summary_ja:
            entry["summaryJa"] = compact_ja(summary_ja)
            if details:
                details["summaryJa"] = summary_ja
        else:
            if UNK in (entry.get("summaryJa") or "") + (details.get("summaryJa") or ""):
                entry["summaryJa"] = ""
                details["summaryJa"] = ""
        impact_ja = ja(details.get("impact") or "", hint)
        if impact_ja:
            details["impactJa"] = impact_ja
        else:
            drop_unk(details, "impactJa")
        jury_ja = ja(details.get("jury") or "", hint)
        if jury_ja:
            details["juryJa"] = jury_ja
        else:
            drop_unk(details, "juryJa")


def translate_job_batch(
    engine,
    items: list[tuple[str, str, str]],
    cache: dict[str, str],
    failed: dict[str, str],
    *,
    retry_beam: int = RETRY_BEAM,
    ollama=None,
    corrections: dict[str, str] | None = None,
    log=print,
) -> None:
    """Translate jobs into `cache`; jobs that still contain <unk> go to `failed`.

    Cache keys come from the ORIGINAL text (collect_jobs); only the text sent to
    the model is normalized.
    """
    pieces: list[tuple[str, str]] = []
    spans: list[tuple[str, int, int]] = []
    for key, lang, text in items:
        start = len(pieces)
        for chunk in split_chunks(normalize_source(text)):
            bad = find_unk_chars(engine.tokenizer, lang, chunk)
            if bad:
                log(f"unk input {key[:8]} {lang} {format_chars(bad)}")
            pieces.append((lang, chunk))
        spans.append((key, start, len(pieces)))
    translated = resolve_pieces(
        engine, pieces, retry_beam=retry_beam, ollama=ollama, corrections=corrections, log=log
    )
    for key, start, end in spans:
        parts = translated[start:end]
        joined = cleanup_ja(" ".join(part for part in parts if part))
        if not parts or None in parts or not joined or UNK in joined:
            failed[key] = next(t for k, _l, t in items if k == key)[:80]
            cache.pop(key, None)
            log(f"untranslated {key[:8]} (left as source)")
            continue
        cache[key] = joined
        failed.pop(key, None)


def is_done(cache: dict[str, str], key: str) -> bool:
    return key in cache and UNK not in cache[key]


def pending_jobs(
    jobs: list[tuple[str, str, str]],
    cache: dict[str, str],
    failed: dict[str, str] | None = None,
) -> list[tuple[str, str, str]]:
    """Jobs still to translate. Known-unresolvable ones (`failed`) are skipped."""
    failed = failed or {}
    return [job for job in jobs if not is_done(cache, job[0]) and job[0] not in failed]


def load_dict(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--titles-ollama", action="store_true")
    parser.add_argument("--skip-titles", action="store_true")
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument(
        "--audit-vocab",
        action="store_true",
        help="list source characters the NLLB tokenizer cannot encode (after normalization), then exit without translating",
    )
    parser.add_argument(
        "--purge-unk",
        action="store_true",
        help="delete <unk>-bearing values from the cache and *Ja fields in public/data/*.json, then exit",
    )
    parser.add_argument("--retry-beam", type=int, default=RETRY_BEAM, help="beam size for the <unk> retry")
    parser.add_argument(
        "--ollama-retry",
        action="store_true",
        help="use local Ollama (--model) as an extra fallback for body text that still has <unk>",
    )
    parser.add_argument("--corrections", type=Path, default=CORRECTIONS_PATH, help="JSON of '<unk>' compound fixes")
    parser.add_argument("--retry-failed", action="store_true", help="retry jobs previously left untranslated")
    args = parser.parse_args(argv)

    if args.purge_unk or args.audit_vocab:
        if args.purge_unk:
            removed = purge_unk(DATA, CACHE_PATH, TITLE_CACHE_PATH)
            for field, count in sorted(removed.items()):
                print(f"purged {field} {count}")
            print(f"purged total {sum(removed.values())}")
            if FAILED_PATH.exists():
                FAILED_PATH.unlink()
        if args.audit_vocab:
            entries_payload = load_json(DATA / "entries.json")
            details = {y: load_json(DATA / f"details-{y}.json") for y in entries_payload["years"]}
            jobs = collect_jobs(entries_payload["entries"], details, year=args.year)
            audit_vocab([(lang, text) for _k, lang, text in jobs], load_tokenizer())
        return

    cache: dict[str, str] = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"cache {len(cache)}")
    title_cache: dict[str, str] = {}
    if TITLE_CACHE_PATH.exists():
        title_cache = json.loads(TITLE_CACHE_PATH.read_text(encoding="utf-8"))
        print(f"title cache {len(title_cache)}")
    failed: dict[str, str] = load_dict(FAILED_PATH)

    entries_payload = load_json(DATA / "entries.json")
    entries = entries_payload["entries"]
    details_by_year: dict[int, dict] = {}
    for year in entries_payload["years"]:
        details_by_year[year] = load_json(DATA / f"details-{year}.json")

    if args.titles_ollama:
        titles = []
        seen = set()
        for entry in entries:
            if args.year and entry["year"] != args.year:
                continue
            title = (entry.get("title") or "").strip()
            if not title or is_japanese(title) or title in seen or is_done(title_cache, title):
                continue
            seen.add(title)
            titles.append(title)
        print(f"titles pending {len(titles)}")
        for index, title in enumerate(titles, start=1):
            try:
                translated = ollama_translate_title(title, args.model)
                if UNK not in translated:
                    title_cache[title] = translated
            except Exception as error:
                print(f"title fail {title[:80]} {error}")
            if index % 10 == 0 or index == len(titles):
                TITLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                TITLE_CACHE_PATH.write_text(json.dumps(title_cache, ensure_ascii=False), encoding="utf-8")
                apply_translations(cache, title_cache, entries, details_by_year)
                patch_into_files(entries, details_by_year)
                print(f"titles {index}/{len(titles)}")
    else:
        jobs = collect_jobs(
            entries,
            details_by_year,
            year=args.year,
            include_titles=not args.skip_titles,
        )
        if args.retry_failed:  # only jobs in scope (--year, --skip-titles)
            for job in jobs:
                failed.pop(job[0], None)
        pending = pending_jobs(jobs, cache, failed)
        print(f"jobs {len(jobs)} pending {len(pending)} skipped-failed {sum(1 for j in jobs if j[0] in failed)}")
        if pending:
            engine = Nllb()
            corrections = load_corrections(args.corrections)
            ollama = None
            if args.ollama_retry:
                if ollama_available():
                    ollama = lambda text: ollama_translate(text, args.model)  # noqa: E731
                else:
                    print("ollama not reachable; skipping that stage")
            print(f"ollama fallback {'on' if ollama else 'off'} corrections {len(corrections)}")
            batch_items: list[tuple[str, str, str]] = []

            flush_count = 0

            def persist() -> None:
                nonlocal flush_count
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                FAILED_PATH.write_text(json.dumps(failed, ensure_ascii=False), encoding="utf-8")
                flush_count += 1
                if flush_count % 3 == 0:
                    apply_translations(cache, title_cache, entries, details_by_year)
                    patch_into_files(entries, details_by_year)

            def translate_jobs(items: list[tuple[str, str, str]]) -> None:
                translate_job_batch(
                    engine, items, cache, failed,
                    retry_beam=args.retry_beam, ollama=ollama, corrections=corrections,
                )

            def flush() -> None:
                if not batch_items:
                    return
                try:
                    translate_jobs(batch_items)
                except Exception as error:
                    print(f"batch fail {error}")
                    for job in list(batch_items):
                        try:
                            translate_jobs([job])
                        except Exception as item_error:
                            print(f"item fail {job[0]} {item_error}")
                batch_items.clear()
                persist()

            for index, job in enumerate(pending, start=1):
                batch_items.append(job)
                if len(batch_items) >= 32:
                    flush()
                    print(f"translated {index}/{len(pending)}", flush=True)
            flush()
            print(f"translated {len(pending)}/{len(pending)}", flush=True)

    apply_translations(cache, title_cache, entries, details_by_year)
    patch_into_files(entries, details_by_year)
    scoped = [entry for entry in entries if not args.year or entry["year"] == args.year]
    with_title = sum(1 for entry in scoped if entry.get("titleJa"))
    with_summary = sum(1 for entry in scoped if entry.get("summaryJa"))
    print(f"wrote titleJa {with_title}/{len(scoped)} summaryJa {with_summary}/{len(scoped)}")


if __name__ == "__main__":
    main()
