#!/usr/bin/env python3
"""Rank GitHub issues for credible, low-spam OSS contributions.

contrib-radar is intentionally LLM-free. It scores issues from `gh issue list --json`
so contributors can pick work that is small, useful, recent, and likely reviewable.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

POSITIVE_LABELS = {
    "good first issue": 18,
    "good-first-issue": 18,
    "help wanted": 14,
    "bug": 8,
    "documentation": 8,
    "docs": 8,
    "testing": 7,
    "tests": 7,
    "enhancement": 5,
}
NEGATIVE_LABELS = {
    "wontfix": -40,
    "invalid": -40,
    "duplicate": -35,
    "stale": -18,
    "blocked": -18,
    "needs design": -12,
    "needs-design": -12,
    "discussion": -10,
}
BROAD_WORDS = re.compile(r"\b(epic|roadmap|architecture|rewrite|migration|tracking|umbrella|rfc)\b", re.I)
CONCRETE_WORDS = re.compile(r"\b(fix|add|update|document|test|error|typo|crash|regression|missing)\b", re.I)
GH_ISSUE_FIELDS = "number,title,body,labels,comments,assignees,updatedAt,url"

@dataclasses.dataclass(frozen=True)
class RankedIssue:
    score: int
    number: int
    title: str
    url: str
    labels: tuple[str, ...]
    reasons: tuple[str, ...]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _label_names(labels: Iterable[Any]) -> tuple[str, ...]:
    names: list[str] = []
    for label in labels or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
    return tuple(names)


def rank_issue(issue: dict[str, Any], now: datetime | None = None) -> RankedIssue:
    now = now or datetime.now(timezone.utc)
    labels = _label_names(issue.get("labels", []))
    label_key = {label.lower(): label for label in labels}
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    text = f"{title}\n{body}"
    score = 50
    reasons: list[str] = []

    for label_lower, original in label_key.items():
        if label_lower in POSITIVE_LABELS:
            delta = POSITIVE_LABELS[label_lower]
            score += delta
            reasons.append(f"+{delta} label:{original}")
        if label_lower in NEGATIVE_LABELS:
            delta = NEGATIVE_LABELS[label_lower]
            score += delta
            reasons.append(f"{delta} label:{original}")

    comments = int(issue.get("comments") or 0)
    if comments == 0:
        score += 8
        reasons.append("+8 no discussion churn")
    elif comments <= 3:
        score += 4
        reasons.append("+4 small discussion")
    elif comments >= 15:
        score -= 12
        reasons.append("-12 high discussion churn")

    if issue.get("assignees"):
        score -= 20
        reasons.append("-20 already assigned")

    if len(title) <= 90:
        score += 4
        reasons.append("+4 focused title")
    if CONCRETE_WORDS.search(text):
        score += 8
        reasons.append("+8 concrete action words")
    if BROAD_WORDS.search(text):
        score -= 16
        reasons.append("-16 broad/planning words")
    if len(body) > 2200:
        score -= 8
        reasons.append("-8 long issue body")

    updated = _parse_time(issue.get("updatedAt") or issue.get("updated_at"))
    if updated:
        days = (now - updated).days
        if days <= 14:
            score += 8
            reasons.append("+8 recently active")
        elif days >= 365:
            score -= 14
            reasons.append("-14 likely stale")

    return RankedIssue(
        score=max(0, min(score, 100)),
        number=int(issue.get("number") or 0),
        title=title,
        url=str(issue.get("url") or ""),
        labels=labels,
        reasons=tuple(reasons),
    )


def rank_issues(issues: Iterable[dict[str, Any]]) -> list[RankedIssue]:
    ranked = [rank_issue(issue) for issue in issues]
    return sorted(ranked, key=lambda issue: (-issue.score, issue.number))


def filter_ranked(ranked: Iterable[RankedIssue], min_score: int | None = None) -> list[RankedIssue]:
    """Return ranked issues that meet the optional minimum score."""
    if min_score is None:
        return list(ranked)
    return [issue for issue in ranked if issue.score >= min_score]


def render_markdown(ranked: list[RankedIssue], limit: int) -> str:
    lines = ["# contrib-radar results", ""]
    for issue in ranked[:limit]:
        labels = ", ".join(issue.labels) if issue.labels else "none"
        reasons = "; ".join(issue.reasons[:4]) if issue.reasons else "baseline score"
        lines.append(f"## {issue.score}/100 · #{issue.number} · {issue.title}")
        if issue.url:
            lines.append(f"URL: {issue.url}")
        lines.append(f"Labels: {labels}")
        lines.append(f"Why: {reasons}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(ranked: list[RankedIssue], limit: int) -> str:
    payload = [dataclasses.asdict(issue) for issue in ranked[:limit]]
    return json.dumps(payload, indent=2) + "\n"


def load_issues_from_gh(repo: str, issue_limit: int) -> list[dict[str, Any]]:
    """Fetch open issues from GitHub using the installed gh CLI."""
    if issue_limit < 1:
        raise SystemExit("--issue-limit must be at least 1")
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(issue_limit),
        "--json",
        GH_ISSUE_FIELDS,
    ]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit("gh CLI is required when using --repo") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout).strip()
        message = "gh issue list failed"
        if details:
            message = f"{message}: {details}"
        raise SystemExit(message) from exc
    data = json.loads(completed.stdout)
    if not isinstance(data, list):
        raise SystemExit("gh returned an unexpected issue payload")
    return data


def load_issues_from_file_or_stdin(path: str | None) -> list[dict[str, Any]]:
    raw = open(path, encoding="utf-8").read() if path else sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit("expected a JSON array of issues")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank GitHub issues for credible OSS contributions.")
    parser.add_argument("file", nargs="?", help="JSON file from gh issue list. Defaults to stdin.")
    parser.add_argument("--repo", help="GitHub repository to fetch directly with gh, for example owner/repo")
    parser.add_argument(
        "--issue-limit",
        type=int,
        default=100,
        help="number of open issues to fetch when --repo is used",
    )
    parser.add_argument("--limit", type=int, default=10, help="number of issues to print")
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="only print issues with this score or higher",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="output format")
    args = parser.parse_args(argv)

    if args.min_score is not None and not 0 <= args.min_score <= 100:
        raise SystemExit("--min-score must be between 0 and 100")

    if args.repo and args.file:
        raise SystemExit("pass either --repo or a JSON file, not both")
    data = (
        load_issues_from_gh(args.repo, args.issue_limit)
        if args.repo
        else load_issues_from_file_or_stdin(args.file)
    )
    ranked = filter_ranked(rank_issues(data), args.min_score)
    if args.format == "json":
        print(render_json(ranked, args.limit), end="")
    else:
        print(render_markdown(ranked, args.limit), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
