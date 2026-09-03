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


def collect_links(row: dict[str, str]) -> list[str]:
    links: list[str] = []
    for key, value in row.items():
        if not key or not value:
            continue
        if not re.search(r"link", key, re.I):
            continue
        url = str(value).strip()
        if url.startswith("http") and url not in links:
            links.append(url)
    return links


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
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return [{(k or "").strip(): v for k, v in row.items()} for row in csv.DictReader(handle)]


def compact_summary(text: str) -> str:
    if len(text) <= SUMMARY_LIMIT:
        return text
    clipped = text[: SUMMARY_LIMIT - 1]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "…"


def merge_existing_ja(entries: list[dict], details_by_year: dict[int, dict[str, dict]]) -> None:
    entries_path = OUT_DIR / "entries.json"
    if entries_path.exists():
        old_entries = {row["id"]: row for row in json.loads(entries_path.read_text(encoding="utf-8")).get("entries", [])}
        for entry in entries:
            previous = old_entries.get(entry["id"], {})
            for key in ("titleJa", "summaryJa", "thumb"):
                if previous.get(key):
                    entry[key] = previous[key]
    for year, records in details_by_year.items():
        path = OUT_DIR / f"details-{year}.json"
        if not path.exists():
            continue
        old_details = json.loads(path.read_text(encoding="utf-8"))
        for entry_id, record in records.items():
            previous = old_details.get(entry_id, {})
            for key in ("summaryJa", "impactJa", "juryJa"):
                if previous.get(key):
                    record[key] = previous[key]


def build() -> None:
    ensure_source()
    index_entries: list[dict] = []
    details_by_year: dict[int, dict[str, dict]] = {}
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
            links = collect_links(row)
            tags = split_tags(row.get("Tags"))
            langs = first(row.get("Language"), row.get("Languages"))
            index_entries.append(
                {
                    "id": entry_id,
                    "year": year,
                    "kind": kind,
                    "title": title,
                    "org": clean_org(first(row.get("Publishing organisations"))),
                    "country": normalize_country(row.get("Country") or ""),
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
                "impact": first(
                    row.get("What was the impact of the project?"),
                    row.get("What was the impact of the project"),
                ),
                "tools": first(
                    row.get("Technologies/tools used"),
                    row.get("Technologies tools used"),
                ),
                "authors": first(row.get("Who made this project"), row.get("Authors")),
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

    print(f"entries {len(index_entries)}")
    print("by year", counts)
    print("wrote", OUT_DIR / "entries.json")


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError as error:
        print(error, file=sys.stderr)
        sys.exit(error.returncode)
