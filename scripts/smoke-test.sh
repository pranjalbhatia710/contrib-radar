#!/usr/bin/env bash
set -euo pipefail
python3 -m unittest discover -p 'test_*.py'
python3 contrib_radar.py examples/sample-issues.json --limit 1 >/tmp/contrib-radar-smoke.md
python3 contrib_radar.py examples/sample-issues.json --format json --limit 1 >/tmp/contrib-radar-smoke.json
python3 contrib_radar.py examples/sample-issues.jsonl --format csv --limit 1 >/tmp/contrib-radar-smoke.csv
if python3 contrib_radar.py examples/sample-issues.json --min-score 101 --fail-on-empty >/tmp/contrib-radar-invalid.out 2>/tmp/contrib-radar-invalid.err; then
  echo "expected invalid min-score check to fail" >&2
  exit 1
fi
if python3 contrib_radar.py examples/sample-issues.json --min-score 100 --fail-on-empty >/tmp/contrib-radar-empty.out 2>/tmp/contrib-radar-empty.err; then
  echo "expected empty candidate check to fail" >&2
  exit 1
fi
