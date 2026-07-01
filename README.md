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

# Focus on bug/docs work and skip known blocked queues before scoring.
python3 contrib_radar.py issues.json \
  --include-label bug \
  --include-label documentation \
  --exclude-label blocked \
  --exclude-label "needs reproduction" \
  --unassigned-only \
  --max-comments 3 \
  --updated-within-days 30 \
  --min-score 80
```

If you already have the GitHub CLI authenticated, you can skip the intermediate
JSON file and fetch open issues directly:

```bash
python3 contrib_radar.py --repo owner/repo --issue-limit 100 --min-score 80 --limit 5
python3 contrib_radar.py --repo owner/repo --include-label "help wanted" --exclude-label blocked --unassigned-only

# Scan a small shortlist of target projects in one ranked pass.
python3 contrib_radar.py \
  --repo owner/agent-project \
  --repo owner/cad-tool \
  --repo owner/robotics-stack \
  --include-label "help wanted" \
  --unassigned-only \
  --max-comments 3

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
```

The direct mode runs `gh issue list` with the same issue fields shown above, then
applies the local scoring model. It still prints the transparent reason string
for every ranked issue.

Use `--unassigned-only`, `--max-comments N`, and `--updated-within-days N` when
you want a contribution session to skip already-owned, high-churn, or stale
issues entirely, rather than merely penalizing them in the score. Use
`--include-text` and `--exclude-text` to focus a session on domain terms or skip
risky phrases before scoring; include terms are OR-ed, while exclude terms always
win. Use `--preset` to add curated include terms for `ai-agents`, `cad`,
`robotics`, `frontend`, or `devtools` without memorizing common project keywords.

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
