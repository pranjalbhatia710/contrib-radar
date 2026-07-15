# contrib-radar

`contrib-radar` ranks GitHub issues for credible OSS contributions.

It is built for people who want to contribute real work without spamming maintainers. Feed it JSON from `gh issue list`, and it highlights issues that are focused, recent, unassigned, and reviewable.

## Why this exists

Most contribution advice optimizes for activity. Maintainers need signal instead:

- small PRs tied to real issues
- docs/tests/bug fixes that can be reviewed quickly
- fewer broad rewrites and stale debates
- less "I want to contribute" noise

`contrib-radar` is a lightweight scoring layer for that workflow.

## Quick start

```bash
gh issue list \
  --repo owner/repo \
  --state open \
  --limit 100 \
  --json number,title,body,labels,comments,assignees,updatedAt,url \
  > issues.json

python3 contrib_radar.py issues.json --limit 10

# Show only high-confidence candidates for a focused contribution session.
python3 contrib_radar.py issues.json --min-score 80 --limit 5

# Treat an empty filtered shortlist as a CI/smoke-test failure.
python3 contrib_radar.py issues.json --min-score 90 --fail-on-empty

# JSON array exports and newline-delimited JSON issue streams are both accepted.
python3 contrib_radar.py examples/sample-issues.jsonl --format csv --limit 10

# Focus on bug/docs work and skip known blocked queues before scoring.
python3 contrib_radar.py issues.json \
  --include-label bug \
  --include-label documentation \
  --exclude-label blocked \
  --exclude-label "needs reproduction" \
  --unassigned-only \
  --max-comments 3 \
  --updated-within-days 30 \
  --created-within-days 180 \
  --min-score 80

# Require an issue to have every included label when you want an intersection
# such as bug + help wanted, not the default union of accepted labels.
python3 contrib_radar.py issues.json \
  --include-label bug \
  --include-label "help wanted" \
  --require-all-labels
```

If you already have the GitHub CLI authenticated, you can skip the intermediate
JSON file and fetch open issues directly:

```bash
python3 contrib_radar.py --repo owner/repo --issue-limit 100 --min-score 80 --limit 5
python3 contrib_radar.py --repo owner/repo --include-label "help wanted" --exclude-label blocked --unassigned-only

# Include compact body previews when deciding whether to open full issues.
python3 contrib_radar.py --repo owner/repo --min-score 80 --show-snippets

# Scan a small shortlist of target projects in one ranked pass.
python3 contrib_radar.py \
  --repo owner/agent-project \
  --repo owner/cad-tool \
  --repo owner/robotics-stack \
  --include-label "help wanted" \
  --unassigned-only \
  --max-comments 3

# Keep recurring scouting targets in a file for daily contribution sessions.
printf "modelcontextprotocol/python-sdk\nCadQuery/cadquery\nhuggingface/lerobot\n" > targets.txt
python3 contrib_radar.py --repo-file targets.txt --preset ai-agents --preset robotics

# Focus a session on a domain and remove risky broad work before scoring.
python3 contrib_radar.py --repo owner/repo \
  --include-text agent \
  --include-text cad \
  --exclude-text "breaking change" \
  --exclude-text migration

# Use curated domain presets for common high-signal contribution areas.
python3 contrib_radar.py \
  --repo modelcontextprotocol/python-sdk \
  --repo CadQuery/cadquery \
  --preset ai-agents \
  --preset cad \
  --exclude-text migration \
  --unassigned-only

# Keep a multi-repo scan useful when one target is private, renamed, or rate-limited.
python3 contrib_radar.py \
  --repo modelcontextprotocol/python-sdk \
  --repo owner/maybe-renamed \
  --skip-fetch-errors \
  --unassigned-only

# Keep one large repo from dominating a multi-project shortlist.
python3 contrib_radar.py \
  --repo modelcontextprotocol/python-sdk \
  --repo CadQuery/cadquery \
  --repo huggingface/lerobot \
  --per-repo-limit 2 \
  --limit 6

# Export a ranked shortlist for spreadsheet review or a daily scouting log.
python3 contrib_radar.py \
  --repo modelcontextprotocol/python-sdk \
  --repo CadQuery/cadquery \
  --format csv \
  --show-snippets \
  --limit 20 > contrib-shortlist.csv
```

The direct mode runs `gh issue list` with the same issue fields shown above, then
applies the local scoring model. It still prints the transparent reason string
for every ranked issue. Use repeated `--repo` flags for a one-off shortlist, or
`--repo-file targets.txt` for newline-delimited recurring target lists; blank
lines and `#` comments are ignored.

Use `--unassigned-only`, `--max-comments N`, and `--updated-within-days N` when
you want a contribution session to skip already-owned, high-churn, or stale
issues entirely, rather than merely penalizing them in the score. Add
`--created-within-days N` when you want to avoid ancient issues that were only
touched recently by bot churn or long-running discussion. Repeated
`--include-label` flags are treated as a union by default; add
`--require-all-labels` when a scan should require every included label. Label
matching is case-insensitive and treats spaces, hyphens, and underscores as
equivalent, so filters such as `--exclude-label "needs reproduction"` also catch
`needs-reproduction` and `needs_reproduction`. Use
`--include-text` and `--exclude-text` to focus a session on domain terms or skip
risky phrases before scoring; include terms are OR-ed, while exclude terms always
win. Use `--preset` to add curated include terms for `ai-agents`, `cad`,
`robotics`, `frontend`, or `devtools` without memorizing common project keywords.
Use `--per-repo-limit N` after scoring to keep multi-repo scans balanced instead
of letting the busiest repository fill the whole shortlist. Use
`--format markdown`, `--format json`, or `--format csv` depending on whether you
want a readable terminal report, machine-readable output, or spreadsheet-friendly
daily scouting log.

Example output:

```text
# contrib-radar results

## 94/100 · #42 · Fix docs typo in install guide
URL: https://github.com/owner/repo/issues/42
Labels: good first issue, documentation
Why: +18 label:good first issue; +8 label:documentation; +8 no discussion churn; +4 focused title
```

## Scoring model

Positive signals:

- `good first issue`, `help wanted`, `bug`, `documentation`, `tests`
- low comment churn
- recent activity
- concrete action words like `fix`, `add`, `update`, `document`, `test`

Negative signals:

- assigned issues
- `stale`, `blocked`, `duplicate`, `wontfix`
- broad planning terms like `epic`, `roadmap`, `rewrite`, `migration`
- very long issue bodies or high discussion churn

The model is intentionally transparent and LLM-free. Every score includes reasons.

## Tests

```bash
python3 -m unittest discover -p 'test_*.py'
```

or:

```bash
python3 -m pytest
```

## Maintainer-first usage

See [docs/maintainer-notes.md](docs/maintainer-notes.md) for the intended workflow. The score is a triage hint, not a license to spam maintainers.

## License

MIT
