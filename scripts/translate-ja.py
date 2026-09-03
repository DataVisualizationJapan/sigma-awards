#!/usr/bin/env python3
"""Translate catalog titles and long fields into Japanese with local NLLB."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
MODEL_DIR = ROOT / ".tmp-data" / "nllb-ct2"
TOKENIZER_DIR = ROOT / ".tmp-data" / "nllb-tok"
CACHE_PATH = ROOT / ".tmp-data" / "ja-cache.json"

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


def patch_into_files(entries: list[dict], details_by_year: dict[int, dict]) -> None:
    payload = load_json(DATA / "entries.json")
    updates = {entry["id"]: entry for entry in entries}
    for row in payload["entries"]:
        source = updates.get(row["id"])
        if not source:
            continue
        for key in ("titleJa", "summaryJa"):
            if source.get(key):
                row[key] = source[key]
    dump_json(DATA / "entries.json", payload)
    for year, records in details_by_year.items():
        path = DATA / f"details-{year}.json"
        current = load_json(path)
        for entry_id, record in records.items():
            if entry_id not in current:
                continue
            for key in ("summaryJa", "impactJa", "juryJa"):
                if record.get(key):
                    current[entry_id][key] = record[key]
        dump_json(path, current)


class Nllb:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / ".venv" / "lib"))
        import ctranslate2
        from transformers import AutoTokenizer

        if not (MODEL_DIR / "model.bin").exists():
            raise SystemExit(f"Missing NLLB model at {MODEL_DIR}")
        tok_src = TOKENIZER_DIR if (TOKENIZER_DIR / "tokenizer.json").exists() or (
            TOKENIZER_DIR / "sentencepiece.bpe.model"
        ).exists() else "facebook/nllb-200-distilled-600M"
        self.tokenizer = AutoTokenizer.from_pretrained(str(tok_src) if tok_src != "facebook/nllb-200-distilled-600M" else tok_src)
        self.translator = ctranslate2.Translator(
            str(MODEL_DIR),
            device="cpu",
            compute_type="int8",
            inter_threads=4,
            intra_threads=2,
        )

    def translate_many(self, items: list[tuple[str, str]]) -> list[str]:
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
                beam_size=1,
                max_batch_size=32,
                max_decoding_length=256,
            )
            for index, result in zip(indexes, results):
                tokens = result.hypotheses[0]
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


def ollama_translate_title(title: str, model: str = "gemma4:e4b") -> str:
    import json as json_lib
    import urllib.request

    prompt = (
        "次の作品タイトルを自然な日本語に翻訳してください。"
        "固有名詞はカタカナや現地の通称を使い、訳文だけを1行で出力してください。"
        "説明や引用符は不要です。\n"
        f"{title}"
    )
    body = json_lib.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "think": False,
            "options": {"temperature": 0, "num_predict": 120},
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json_lib.loads(response.read().decode())
    text = (payload.get("response") or "").strip()
    line = next((row.strip() for row in text.splitlines() if row.strip()), "")
    return cleanup_ja(line.strip('「」""\' '))


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
        return cache.get(cache_key(lang, text), "")

    for entry in entries:
        hint = entry.get("langs") or ""
        details = details_by_year.get(entry["year"], {}).get(entry["id"], {})
        title_ja = title_cache.get(entry.get("title") or "") or ja(entry.get("title") or "", hint)
        summary_full = details.get("summary") or entry.get("summary") or ""
        summary_ja = ja(summary_full, hint)
        if title_ja:
            entry["titleJa"] = title_ja
        if summary_ja:
            entry["summaryJa"] = compact_ja(summary_ja)
            if details:
                details["summaryJa"] = summary_ja
        impact_ja = ja(details.get("impact") or "", hint)
        if impact_ja:
            details["impactJa"] = impact_ja
        jury_ja = ja(details.get("jury") or "", hint)
        if jury_ja:
            details["juryJa"] = jury_ja


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--titles-ollama", action="store_true")
    parser.add_argument("--skip-titles", action="store_true")
    parser.add_argument("--model", default="gemma4:e4b")
    args = parser.parse_args()

    cache: dict[str, str] = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"cache {len(cache)}")
    title_cache: dict[str, str] = {}
    if TITLE_CACHE_PATH.exists():
        title_cache = json.loads(TITLE_CACHE_PATH.read_text(encoding="utf-8"))
        print(f"title cache {len(title_cache)}")

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
            if not title or is_japanese(title) or title in seen or title in title_cache:
                continue
            seen.add(title)
            titles.append(title)
        print(f"titles pending {len(titles)}")
        for index, title in enumerate(titles, start=1):
            try:
                title_cache[title] = ollama_translate_title(title, args.model)
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
        pending = [(key, lang, text) for key, lang, text in jobs if key not in cache]
        print(f"jobs {len(jobs)} pending {len(pending)}")
        if pending:
            engine = Nllb()
            batch_items: list[tuple[str, str, str]] = []

            flush_count = 0

            def persist() -> None:
                nonlocal flush_count
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                flush_count += 1
                if flush_count % 3 == 0:
                    apply_translations(cache, title_cache, entries, details_by_year)
                    patch_into_files(entries, details_by_year)

            def translate_jobs(items: list[tuple[str, str, str]]) -> None:
                pieces: list[tuple[str, str]] = []
                spans: list[tuple[str, int, int]] = []
                for key, lang, text in items:
                    chunks = split_chunks(text)
                    start = len(pieces)
                    for chunk in chunks:
                        pieces.append((lang, chunk))
                    spans.append((key, start, len(pieces)))
                translated = engine.translate_many(pieces)
                for key, start, end in spans:
                    cache[key] = cleanup_ja(" ".join(part for part in translated[start:end] if part))

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
