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
```

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

## License

MIT
