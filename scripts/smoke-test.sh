#!/usr/bin/env bash
set -euo pipefail
python3 -m unittest discover -p 'test_*.py'
python3 contrib_radar.py examples/sample-issues.json --limit 1 >/tmp/contrib-radar-smoke.md
python3 contrib_radar.py examples/sample-issues.json --format json --limit 1 >/tmp/contrib-radar-smoke.json
