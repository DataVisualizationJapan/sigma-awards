#!/bin/bash
set -u
cd "$(dirname "$0")/.."
LOG=".tmp-data/translate.log"
mkdir -p .tmp-data
echo "==== start $(date) pid $$ ====" >> "$LOG"
while true; do
  PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/translate-ja.py >> "$LOG" 2>&1
  code=$?
  echo "==== exit $code $(date) ====" >> "$LOG"
  leftover="$(.venv/bin/python - <<'PY'
import json
import importlib.util

spec = importlib.util.spec_from_file_location("t", "scripts/translate-ja.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
payload = mod.load_json(mod.DATA / "entries.json")
entries = payload["entries"]
details = {y: mod.load_json(mod.DATA / f"details-{y}.json") for y in payload["years"]}
cache = mod.load_dict(mod.CACHE_PATH)
failed = mod.load_dict(mod.FAILED_PATH)
jobs = mod.collect_jobs(entries, details, include_titles=True)
print(len(mod.pending_jobs(jobs, cache, failed)))
PY
)"
  echo "pending $leftover" >> "$LOG"
  if [ "$leftover" = "0" ]; then
    echo "==== done $(date) ====" >> "$LOG"
    break
  fi
  echo "==== restart pending=$leftover $(date) ====" >> "$LOG"
  sleep 3
done
