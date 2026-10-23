#!/usr/bin/env python3
"""Normalize Sigma Awards CSVs into compact JSON for the catalog UI."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sigma_text import blank_placeholder, decode_entities, normalize_links, read_text_lines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = Path(os.environ.get("SIGMA_DATA_DIR", ROOT / ".tmp-data"))
SOURCE_REPO = "https://github.com/Sigma-Awards/The-Sigma-Awards-projects-data.git"
OUT_DIR = ROOT / "public" / "data"

FILES = [
    (2020, "The Sigma Awards 2020-single projects.csv", "project"),
    (2020, "The Sigma Awards 2020-portfolios.csv", "portfolio"),
    (2021, "The Sigma Awards 2021-single projects.csv", "project"),
    (2021, "The Sigma Awards 2021-portfolios.csv", "portfolio"),
    (2022, "The Sigma Awards 2022-single projects.csv", "project"),
    (2022, "The Sigma Awards 2022-portfolios.csv", "portfolio"),
    (2023, "The Sigma Awards 2023-single projects.csv", "project"),
    (2023, "The Sigma Awards 2023-portfolios.csv", "portfolio"),
    (2024, "The Sigma Awards 2024-single projects.csv", "project"),
    (2024, "The Sigma Awards 2024-portfolios.csv", "portfolio"),
    (2025, "The Sigma Awards 2025-single projects.csv", "project"),
    (2025, "The Sigma Awards 2025-portfolios.csv", "portfolio"),
    (2026, "The Sigma Awards 2026-single-project.csv", "project"),
    (2026, "The Sigma Awards 2026-portfolios.csv", "portfolio"),
]

COUNTRY_ALIASES = {
    "United States of America": "United States",
    "USA": "United States",
    "US": "United States",
    "UK": "United Kingdom",
    "The Netherlands": "Netherlands",
    "Holland": "Netherlands",
}

SUMMARY_LIMIT = 240
UNK = "<unk>"
LINK_KEY = re.compile(r"link", re.I)
PLACEHOLDER_FIELDS = {"org", "country", "authors", "tools", "impact"}


def first(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return re.sub(r"\s+", " ", text)
    return ""


def split_tags(value: object) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[,;/|]", str(value)):
        tag = part.strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def collect_links(row: dict[str, str]) -> tuple[list[str], list[dict]]:
    cells: list[str] = []
    for key, value in row.items():
        if not key or not value:
            continue
        if not LINK_KEY.search(key):
            continue
        url = str(value).strip()
        if url.startswith("http"):
            cells.append(url)
    return normalize_links(cells)


def normalize_country(value: str) -> str:
    country = first(value)
    return COUNTRY_ALIASES.get(country, country)


def clean_org(value: str) -> str:
    text = re.sub(r"https?://\S+", " ", value)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\(\s*$", " ", text)
    return first(text)


def normalize_result(value: object) -> tuple[str, str]:
    raw = first(value)
    if not raw or raw.lower() == "participant":
        return "entry", "Entry"
    low = raw.lower()
    if "winner" in low:
        return "winner", raw
    if "shortlist" in low:
        return "shortlist", raw
    if "citation" in low or "honorable" in low or "mention" in low:
        return "mention", raw
    return "entry", raw


def ensure_source() -> None:
    marker = SOURCE_DIR / "The Sigma Awards 2026-single-project.csv"
    if marker.exists():
        return
    SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if SOURCE_DIR.exists():
        raise SystemExit(f"Incomplete source directory: {SOURCE_DIR}")
    subprocess.check_call(["git", "clone", "--depth", "1", SOURCE_REPO, str(SOURCE_DIR)])


def load_rows(path: Path) -> list[dict[str, str]]:
    reader = csv.DictReader(read_text_lines(path.read_bytes()))
    rows = []
    for row in reader:
        out: dict[str, str] = {}
        for key, value in row.items():
            name = decode_entities(key or "").strip()
            # Link cells keep their upstream text so url-fixes.json can show the original.
            is_link = isinstance(value, str) and LINK_KEY.search(name)
            out[name] = decode_entities(value) if isinstance(value, str) and not is_link else value
        rows.append(out)
    return rows


def compact_summary(text: str) -> str:
    if len(text) <= SUMMARY_LIMIT:
        return text
    clipped = text[: SUMMARY_LIMIT - 1]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "…"


def source_text(field: str, value: object) -> str:
    """Normalize an existing JSON source value the way the build does."""
    text = first(decode_entities(str(value or "")))
    return blank_placeholder(text) if field in PLACEHOLDER_FIELDS else text


def carry_ja(
    target: dict,
    previous: dict,
    old_source: object,
    key: str,
    source_key: str,
    scope: str,
    stats: dict[str, dict[str, int]],
) -> None:
    """Copy previous[key] into target unless its source text changed or it is unusable."""
    if not previous.get(key):
        return
    bucket = stats.setdefault(f"{scope}.{key}", {"kept": 0, "source-changed": 0, "source-empty": 0, "unk": 0})
    new_source = target.get(source_key) or ""
    if not new_source:
        bucket["source-empty"] += 1
    elif source_text(source_key, old_source) != new_source:
        bucket["source-changed"] += 1
    elif UNK in previous[key]:
        bucket["unk"] += 1
    else:
        target[key] = decode_entities(previous[key])
        bucket["kept"] += 1


def merge_existing_ja(entries: list[dict], details_by_year: dict[int, dict[str, dict]]) -> None:
    stats: dict[str, dict[str, int]] = {}
    entries_path = OUT_DIR / "entries.json"
    old_details_by_year: dict[int, dict] = {}
    for year in details_by_year:
        path = OUT_DIR / f"details-{year}.json"
        old_details_by_year[year] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if entries_path.exists():
        old_entries = {row["id"]: row for row in json.loads(entries_path.read_text(encoding="utf-8")).get("entries", [])}
        for entry in entries:
            previous = old_entries.get(entry["id"], {})
            if previous.get("thumb"):
                entry["thumb"] = previous["thumb"]
            old_detail = old_details_by_year.get(entry["year"], {}).get(entry["id"], {})
            full_summary = details_by_year[entry["year"]][entry["id"]]["summary"]
            carry_ja(entry, previous, previous.get("title"), "titleJa", "title", "entries", stats)
            # entries.summaryJa translates the full summary, which the entry only holds compacted.
            summary_target = {"summary": full_summary}
            carry_ja(summary_target, previous, old_detail.get("summary", previous.get("summary")), "summaryJa", "summary", "entries", stats)
            if summary_target.get("summaryJa"):
                entry["summaryJa"] = summary_target["summaryJa"]
    for year, records in details_by_year.items():
        old_details = old_details_by_year[year]
        for entry_id, record in records.items():
            previous = old_details.get(entry_id, {})
            for key, source_key in (("summaryJa", "summary"), ("impactJa", "impact"), ("juryJa", "jury")):
                carry_ja(record, previous, previous.get(source_key), key, source_key, "details", stats)
    print("Japanese translations carried over (kept / dropped by reason):")
    for name in sorted(stats):
        bucket = stats[name]
        dropped = sum(bucket.values()) - bucket["kept"]
        print(
            f"  {name}: kept {bucket['kept']}, dropped {dropped}"
            f" (source-changed {bucket['source-changed']}, source-empty {bucket['source-empty']}, <unk> {bucket['unk']})"
        )


def build() -> None:
    ensure_source()
    index_entries: list[dict] = []
    details_by_year: dict[int, dict[str, dict]] = {}
    url_fixes: list[dict] = []
    counts = {2020: 0, 2021: 0, 2022: 0, 2023: 0, 2024: 0, 2025: 0, 2026: 0}

    for year, filename, kind in FILES:
        path = SOURCE_DIR / filename
        if not path.exists():
            raise SystemExit(f"Missing {path}")
        sequential = 0
        for row in load_rows(path):
            title = first(row.get("Project title"))
            if not title:
                continue
            prefix = "s" if kind == "project" else "f"
            sequential += 1
            entry_id = f"{year}-{prefix}-{sequential:04d}"
            result_key, result_label = normalize_result(row.get("Results"))
            summary = first(
                row.get("A short description of the project"),
                row.get("Description of your portfolio"),
                row.get("Description portfolio"),
            )
            links, fixes = collect_links(row)
            url_fixes.extend({"id": entry_id, "field": "links", **fix} for fix in fixes)
            tags = split_tags(row.get("Tags"))
            langs = first(row.get("Language"), row.get("Languages"))
            index_entries.append(
                {
                    "id": entry_id,
                    "year": year,
                    "kind": kind,
                    "title": title,
                    "org": blank_placeholder(clean_org(first(row.get("Publishing organisations")))),
                    "country": blank_placeholder(normalize_country(row.get("Country") or "")),
                    "result": result_key,
                    "resultLabel": result_label,
                    "tags": tags,
                    "summary": compact_summary(summary),
                    "langs": langs,
                    "url": links[0] if links else "",
                }
            )
            details_by_year.setdefault(year, {})[entry_id] = {
                "summary": summary,
                "impact": blank_placeholder(
                    first(
                        row.get("What was the impact of the project?"),
                        row.get("What was the impact of the project"),
                    )
                ),
                "tools": blank_placeholder(
                    first(
                        row.get("Technologies/tools used"),
                        row.get("Technologies tools used"),
                    )
                ),
                "authors": blank_placeholder(first(row.get("Who made this project"), row.get("Authors"))),
                "langs": first(row.get("Language"), row.get("Languages")),
                "date": first(row.get("Publication date")),
                "size": first(row.get("Size"), row.get("Organisation size")),
                "jury": first(row.get("Jury's comments")),
                "links": links,
            }
        counts[year] += sequential

    merge_existing_ja(index_entries, details_by_year)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": SOURCE_REPO.replace(".git", ""),
        "license": "CC BY-NC-SA 4.0",
        "attribution": "The Sigma Awards / Global Investigative Journalism Network (GIJN)",
        "site": "https://sigmaawards.org",
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(index_entries),
        "years": sorted({entry["year"] for entry in index_entries}),
        "entries": index_entries,
    }
    (OUT_DIR / "entries.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    for year, records in details_by_year.items():
        (OUT_DIR / f"details-{year}.json").write_text(
            json.dumps(records, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    (OUT_DIR / "url-fixes.json").write_text(
        json.dumps({"count": len(url_fixes), "fixes": url_fixes}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    print(f"entries {len(index_entries)}")
    print(f"url fixes {len(url_fixes)}")
    print("by year", counts)
    print("wrote", OUT_DIR / "entries.json")


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError as error:
        print(error, file=sys.stderr)
        sys.exit(error.returncode)
