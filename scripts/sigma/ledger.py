"""ID ledger: keeps Sigma entry IDs stable when the upstream CSVs change.

Upstream has no submission key, so each upstream row is matched to a ledger
entry by fingerprint. IDs are never renumbered and never reused.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent / "ids.json"
VERSION = 1
PREFIX = {"project": "s", "portfolio": "f"}
MIN_SCORE = 4
SCORE_LIMIT_MAX = 20
SCORE_LIMIT_MIN = 3
SCORE_LIMIT_RATIO = 0.10

DESCRIPTION_KEYS = (
    "A short description of the project",
    "Description of your portfolio",
    "Description portfolio",
)


class LedgerError(Exception):
    """Matching cannot continue without a human decision."""


def _sha(text: str, size: int = 16) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:size]


def norm_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def norm_link(value: str) -> str:
    url = value.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.split("#", 1)[0]
    return url.rstrip("/")


def row_hash(row: dict[str, str]) -> str:
    pairs = sorted(
        (key.strip(), "".join(str(value).split()))
        for key, value in row.items()
        if key and key.strip() and value and "".join(str(value).split())
    )
    return _sha(json.dumps(pairs, ensure_ascii=False))


def fingerprint(row: dict[str, str]) -> dict:
    links = set()
    for key, value in row.items():
        if key and value and re.search(r"link", key, re.I) and str(value).strip().startswith("http"):
            links.add(norm_link(str(value)))
    description = ""
    for key in DESCRIPTION_KEYS:
        if row.get(key) and str(row[key]).strip():
            description = norm_text(row[key])
            break
    return {
        "rowHash": row_hash(row),
        "title": norm_text(row.get("Project title")),
        "org": norm_text(row.get("Publishing organisations")),
        "links": sorted(links),
        "desc": _sha(description, 12) if description else "",
        "category": norm_text(row.get("Category")),
    }


def score(up: dict, led: dict) -> int:
    total = 0
    if up["title"] and up["title"] == led["title"]:
        total += 3
    a, b = set(up["links"]), set(led["links"])
    if a and b:
        if a == b:
            total += 2
        elif a & b:
            total += 1
    if up["desc"] and up["desc"] == led["desc"]:
        total += 2
    if up["org"] and up["org"] == led["org"]:
        total += 1
    if up["category"] and up["category"] == led["category"]:
        total += 1
    return total


def empty_ledger() -> dict:
    return {"version": VERSION, "upstreamCommit": None, "overrides": {}, "entries": {}}


def load(path: Path = LEDGER_PATH) -> dict:
    if not path.exists():
        return empty_ledger()
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("overrides", {})
    return data


def save(ledger: dict, path: Path = LEDGER_PATH) -> None:
    head = {k: v for k, v in ledger.items() if k != "entries"}
    entries = ledger["entries"]
    rows = [f'  {json.dumps(i)}:{json.dumps(entries[i], ensure_ascii=False, separators=(",", ":"))}' for i in sorted(entries)]
    top = ",\n".join(f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in head.items())
    path.write_text("{\n" + top + ',\n "entries": {\n' + ",\n".join(rows) + "\n }\n}\n", encoding="utf-8")


def make_id(year: int, kind: str, number: int) -> str:
    return f"{year}-{PREFIX[kind]}-{number:04d}"


def _number(entry_id: str) -> int:
    return int(entry_id.rsplit("-", 1)[1])


def score_limit(rows: int) -> int:
    return max(SCORE_LIMIT_MIN, min(SCORE_LIMIT_MAX, math.ceil(rows * SCORE_LIMIT_RATIO)))


def reconcile(ledger: dict, year: int, kind: str, rows: list[dict[str, str]]) -> tuple[list[str], dict]:
    """Return the ID of each upstream row (same order) and mutate the ledger.

    `rows` are the raw CSV rows that have a project title.
    """
    entries = ledger["entries"]
    group = {i: e for i, e in entries.items() if e["year"] == year and e["kind"] == kind}
    ups = [fingerprint(r) for r in rows]
    assigned: dict[int, str] = {}
    taken: set[str] = set()
    report = {"year": year, "kind": kind, "confirmed": [], "scored": [], "new": [], "removed": [], "overrides": []}

    def assign(index: int, entry_id: str, how: str, points: int | None = None) -> None:
        assigned[index] = entry_id
        taken.add(entry_id)
        report[how].append((entry_id, points) if points is not None else entry_id)

    # 0. Manual overrides pin an ID to an upstream row hash.
    for entry_id, wanted in sorted(ledger.get("overrides", {}).items()):
        if entry_id not in group or entry_id in taken:
            continue
        for index, up in enumerate(ups):
            if index not in assigned and up["rowHash"] == wanted:
                assign(index, entry_id, "overrides")
                break

    # 1. Whole-row hash that is unique (or equally repeated) on both sides.
    up_by_hash: dict[str, list[int]] = {}
    for index, up in enumerate(ups):
        if index not in assigned:
            up_by_hash.setdefault(up["rowHash"], []).append(index)
    led_by_hash: dict[str, list[str]] = {}
    for entry_id in sorted(group):
        if entry_id not in taken:
            led_by_hash.setdefault(group[entry_id]["rowHash"], []).append(entry_id)
    for digest, indexes in up_by_hash.items():
        ids = led_by_hash.get(digest, [])
        if len(indexes) == len(ids):
            for index, entry_id in zip(indexes, ids):  # identical rows are interchangeable
                assign(index, entry_id, "confirmed")

    # 2. Score the rest, best pairs first, one-to-one.
    free_up = [i for i in range(len(ups)) if i not in assigned]
    free_led = [i for i in sorted(group) if i not in taken]
    pairs = []
    for index in free_up:
        for entry_id in free_led:
            points = score(ups[index], group[entry_id])
            if points >= MIN_SCORE:
                pairs.append((points, index, entry_id))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    scored = 0
    for points, index, entry_id in pairs:
        if index in assigned or entry_id in taken:
            continue
        rivals = [
            p for p in pairs
            if p[0] == points and (p[1], p[2]) != (index, entry_id)
            and (p[1] == index or p[2] == entry_id)
            and p[1] not in assigned and p[2] not in taken
        ]
        if rivals:
            lines = [f"  row {index + 1} ({rows[index].get('Project title', '')!r}) ~ {entry_id} [{points}pt]"]
            lines += [f"  row {r[1] + 1} ~ {r[2]} [{r[0]}pt]" for r in rivals]
            raise LedgerError(
                f"Ambiguous match in {year} {kind}: candidates tie.\n" + "\n".join(lines)
                + "\nPin one in scripts/sigma/ids.json under \"overrides\": {\"<id>\": \"<row hash>\"}."
            )
        assign(index, entry_id, "scored", points)
        scored += 1
    limit = score_limit(len(ups))
    if scored > limit:
        raise LedgerError(
            f"{scored} rows in {year} {kind} matched by score (limit {limit}); upstream changed too much to trust.\n"
            + "\n".join(f"  {i} [{p}pt]" for i, p in report["scored"][:30])
            + "\nReview the upstream diff, then pin IDs under \"overrides\" in scripts/sigma/ids.json."
        )

    # 3. Anything left is new; numbers only ever grow.
    top = max((_number(i) for i in group), default=0)
    for index in range(len(ups)):
        if index not in assigned:
            top += 1
            entry_id = make_id(year, kind, top)
            assign(index, entry_id, "new")

    # 4. Persist fingerprints; unmatched ledger IDs stay as removed.
    for index, entry_id in assigned.items():
        entries[entry_id] = {"year": year, "kind": kind, **ups[index], "removed": False}
    for entry_id in group:
        if entry_id not in taken:
            if not entries[entry_id].get("removed"):
                report["removed"].append(entry_id)
            entries[entry_id]["removed"] = True
    return [assigned[i] for i in range(len(ups))], report


def format_report(reports: list[dict]) -> str:
    out = ["ID ledger:"]
    totals = {k: 0 for k in ("confirmed", "scored", "new", "removed", "overrides")}
    for rep in reports:
        for key in totals:
            totals[key] += len(rep[key])
        if rep["scored"] or rep["new"] or rep["removed"] or rep["overrides"]:
            out.append(f"  {rep['year']} {rep['kind']}:")
            for entry_id, points in rep["scored"]:
                out.append(f"    scored  {entry_id} ({points}pt)")
            for entry_id in rep["overrides"]:
                out.append(f"    override {entry_id}")
            for label, ids in (("new", rep["new"]), ("removed", rep["removed"])):
                if len(ids) > 10:
                    out.append(f"    {label:<8}{len(ids)} IDs ({ids[0]} .. {ids[-1]})")
                else:
                    out.extend(f"    {label:<8}{entry_id}" for entry_id in ids)
    out.append("  totals: " + ", ".join(f"{k} {v}" for k, v in totals.items()))
    return "\n".join(out)
