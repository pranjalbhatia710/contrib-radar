#!/usr/bin/env python3
"""Rank GitHub issues for credible, low-spam OSS contributions.

contrib-radar is intentionally LLM-free. It scores issues from `gh issue list --json`
so contributors can pick work that is small, useful, recent, and likely reviewable.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import re
import subprocess
import sys
from io import StringIO
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
LABEL_ALIASES = {
    "docs": "documentation",
    "doc": "documentation",
    "good-first-issue": "good first issue",
    "good first issue": "good first issue",
    "help-wanted": "help wanted",
    "help wanted": "help wanted",
    "test": "tests",
    "testing": "tests",
}
DOMAIN_PRESETS = {
    "ai-agents": ("agent", "mcp", "llm", "tool call", "prompt", "eval"),
    "cad": ("cad", "geometry", "mesh", "step", "stl", "workplane"),
    "robotics": ("robot", "robotics", "dataset", "teleop", "policy", "simulation"),
    "frontend": ("frontend", "ui", "ux", "accessibility", "a11y", "component"),
    "devtools": ("cli", "developer experience", "dx", "configuration", "install", "debug"),
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
    repository: str
    labels: tuple[str, ...]
    reasons: tuple[str, ...]
    body_snippet: str


def _parse_time(value: str | None) -> datetime | None:
    """Parse a GitHub-style timestamp and normalize it to timezone-aware UTC.

    GitHub's API returns offset-aware timestamps such as
    ``2026-06-01T00:00:00Z``, but imported issue exports often contain naive ISO
    strings. Treat those as UTC so activity filters and scoring do not crash when
    subtracting from an aware ``now`` value.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _label_names(labels: Iterable[Any]) -> tuple[str, ...]:
    names: list[str] = []
    for label in labels or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
    return tuple(names)


def _comment_count(value: Any) -> int:
    """Return a comment count from gh's count or node-list representations."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _body_snippet(body: str, limit: int = 240) -> str:
    """Return a compact one-line issue-body preview for terminal triage."""
    compact = re.sub(r"\s+", " ", body).strip()
    if not compact:
        return ""
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


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
        label_score_key = _canonical_label(label_lower)
        if label_score_key in POSITIVE_LABELS:
            delta = POSITIVE_LABELS[label_score_key]
            score += delta
            reasons.append(f"+{delta} label:{original}")
        if label_score_key in NEGATIVE_LABELS:
            delta = NEGATIVE_LABELS[label_score_key]
            score += delta
            reasons.append(f"{delta} label:{original}")

    comments = _comment_count(issue.get("comments"))
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
        repository=str(issue.get("repository") or ""),
        labels=labels,
        reasons=tuple(reasons),
        body_snippet=_body_snippet(body),
    )


def rank_issues(issues: Iterable[dict[str, Any]]) -> list[RankedIssue]:
    ranked = [rank_issue(issue) for issue in issues]
    return sorted(ranked, key=lambda issue: (-issue.score, issue.number))


def filter_ranked(ranked: Iterable[RankedIssue], min_score: int | None = None) -> list[RankedIssue]:
    """Return ranked issues that meet the optional minimum score."""
    if min_score is None:
        return list(ranked)
    return [issue for issue in ranked if issue.score >= min_score]


def limit_ranked_per_repo(ranked: Iterable[RankedIssue], per_repo_limit: int | None = None) -> list[RankedIssue]:
    """Cap ranked output per repository while preserving global rank order.

    Multi-repo scans can otherwise be dominated by one busy project. Empty
    repository names share the same bucket, which keeps imported JSON without a
    source repository deterministic.
    """
    if per_repo_limit is None:
        return list(ranked)
    seen: dict[str, int] = {}
    limited: list[RankedIssue] = []
    for issue in ranked:
        repository = issue.repository
        count = seen.get(repository, 0)
        if count >= per_repo_limit:
            continue
        seen[repository] = count + 1
        limited.append(issue)
    return limited


def _canonical_label(label: str) -> str:
    """Normalize GitHub label spelling for filters and scoring.

    Repositories vary between space, hyphen, and underscore spellings for the
    same workflow labels (for example ``help wanted``, ``help-wanted``, and
    ``help_wanted``). Treat those separators as equivalent so a contributor's
    include/exclude filter keeps working across projects.
    """
    normalized = re.sub(r"[-_]+", " ", label.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return LABEL_ALIASES.get(normalized, normalized)


def _normalize_label_filters(labels: Iterable[str] | None) -> set[str]:
    return {_canonical_label(label) for label in labels or [] if label.strip()}


def filter_issues_by_label(
    issues: Iterable[dict[str, Any]],
    *,
    include_labels: Iterable[str] | None = None,
    exclude_labels: Iterable[str] | None = None,
    require_all_include_labels: bool = False,
) -> list[dict[str, Any]]:
    """Filter raw issues before ranking using case-insensitive label names.

    Include filters are OR-ed: an issue passes when it has at least one requested
    label. Set ``require_all_include_labels`` when a session needs intersections
    such as ``bug`` + ``help wanted`` instead of the default union. Exclude
    filters always win, which lets contributors avoid queues such as `blocked`
    or `needs reproduction` even when they also carry positive tags.
    """
    include = _normalize_label_filters(include_labels)
    exclude = _normalize_label_filters(exclude_labels)
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        labels = {_canonical_label(label) for label in _label_names(issue.get("labels", []))}
        if include:
            if require_all_include_labels:
                if not include.issubset(labels):
                    continue
            elif labels.isdisjoint(include):
                continue
        if exclude and not labels.isdisjoint(exclude):
            continue
        filtered.append(issue)
    return filtered


def filter_issues_by_workflow(
    issues: Iterable[dict[str, Any]],
    *,
    unassigned_only: bool = False,
    max_comments: int | None = None,
) -> list[dict[str, Any]]:
    """Filter raw issues for contribution-session workflow constraints.

    These filters are intentionally separate from scoring: sometimes contributors
    need to completely skip assigned or high-churn issues instead of merely
    ranking them lower.
    """
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        if unassigned_only and issue.get("assignees"):
            continue
        if max_comments is not None and _comment_count(issue.get("comments")) > max_comments:
            continue
        filtered.append(issue)
    return filtered


def filter_issues_by_activity(
    issues: Iterable[dict[str, Any]],
    *,
    updated_within_days: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Filter raw issues by recent maintainer or reporter activity.

    Issues without a parseable `updatedAt` timestamp are skipped when the filter
    is active. That keeps focused contribution sessions from accidentally
    targeting stale imported data.
    """
    if updated_within_days is None:
        return list(issues)
    now = now or datetime.now(timezone.utc)
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        updated = _parse_time(issue.get("updatedAt") or issue.get("updated_at"))
        if not updated:
            continue
        if (now - updated).days <= updated_within_days:
            filtered.append(issue)
    return filtered


def filter_issues_by_text(
    issues: Iterable[dict[str, Any]],
    *,
    include_terms: Iterable[str] | None = None,
    exclude_terms: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter raw issues by case-insensitive title/body text matches.

    Include terms are OR-ed so a focused session can accept any of several
    domains, such as `cad`, `robot`, or `agent`. Exclude terms always win to
    remove risky queues like `breaking change` or `needs reproduction`.
    """
    include = tuple(term.casefold() for term in include_terms or [] if term.strip())
    exclude = tuple(term.casefold() for term in exclude_terms or [] if term.strip())
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        haystack = f"{issue.get('title') or ''}\n{issue.get('body') or ''}".casefold()
        if include and not any(term in haystack for term in include):
            continue
        if exclude and any(term in haystack for term in exclude):
            continue
        filtered.append(issue)
    return filtered


def expand_preset_terms(presets: Iterable[str], include_terms: Iterable[str] | None = None) -> list[str]:
    """Return include-text terms with domain preset terms appended in CLI order."""
    expanded = [term for term in include_terms or [] if term.strip()]
    for preset in presets:
        try:
            expanded.extend(DOMAIN_PRESETS[preset])
        except KeyError as exc:
            choices = ", ".join(sorted(DOMAIN_PRESETS))
            raise SystemExit(f"unknown --preset {preset!r}; choose one of: {choices}") from exc
    return expanded


def render_markdown(ranked: list[RankedIssue], limit: int, *, show_snippets: bool = False) -> str:
    lines = ["# contrib-radar results", ""]
    for issue in ranked[:limit]:
        labels = ", ".join(issue.labels) if issue.labels else "none"
        reasons = "; ".join(issue.reasons[:4]) if issue.reasons else "baseline score"
        lines.append(f"## {issue.score}/100 · #{issue.number} · {issue.title}")
        if issue.url:
            lines.append(f"URL: {issue.url}")
        if issue.repository:
            lines.append(f"Repo: {issue.repository}")
        if show_snippets and issue.body_snippet:
            lines.append(f"Snippet: {issue.body_snippet}")
        lines.append(f"Labels: {labels}")
        lines.append(f"Why: {reasons}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(ranked: list[RankedIssue], limit: int) -> str:
    payload = [dataclasses.asdict(issue) for issue in ranked[:limit]]
    return json.dumps(payload, indent=2) + "\n"


def render_csv(ranked: list[RankedIssue], limit: int, *, show_snippets: bool = False) -> str:
    """Return ranked issues as CSV for spreadsheets and daily scouting logs."""
    output = StringIO(newline="")
    fieldnames = [
        "score",
        "number",
        "title",
        "url",
        "repository",
        "labels",
        "reasons",
    ]
    if show_snippets:
        fieldnames.append("body_snippet")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for issue in ranked[:limit]:
        row = {
            "score": issue.score,
            "number": issue.number,
            "title": issue.title,
            "url": issue.url,
            "repository": issue.repository,
            "labels": "; ".join(issue.labels),
            "reasons": "; ".join(issue.reasons),
        }
        if show_snippets:
            row["body_snippet"] = issue.body_snippet
        writer.writerow(row)
    return output.getvalue()


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


def load_issues_from_repos(
    repos: Iterable[str],
    issue_limit: int,
    *,
    skip_fetch_errors: bool = False,
) -> list[dict[str, Any]]:
    """Fetch open issues from one or more GitHub repositories.

    Multi-repo scouting is intentionally a thin wrapper around the single-repo
    loader so failures still name the repository that blocked the scan.
    """
    combined: list[dict[str, Any]] = []
    saw_repo = False
    for repo in repos:
        repo = repo.strip()
        if not repo:
            continue
        saw_repo = True
        try:
            issues = load_issues_from_gh(repo, issue_limit)
        except SystemExit as exc:
            if not skip_fetch_errors:
                raise SystemExit(f"{repo}: {exc}") from exc
            print(f"warning: skipped {repo}: {exc}", file=sys.stderr)
            continue
        for issue in issues:
            issue.setdefault("repository", repo)
        combined.extend(issues)
    if not saw_repo:
        raise SystemExit("at least one non-empty --repo value is required")
    if skip_fetch_errors and not combined:
        raise SystemExit("all repository fetches failed or returned no issues")
    return combined


def load_repos_from_file(path: str) -> list[str]:
    """Load newline-delimited repositories, ignoring blank lines and comments."""
    repos: list[str] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "#" in line:
                    line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                if "/" not in line:
                    raise SystemExit(f"{path}:{line_number}: expected owner/repo, got {line!r}")
                repos.append(line)
    except OSError as exc:
        raise SystemExit(f"could not read --repo-file {path!r}: {exc.strerror}") from exc
    if not repos:
        raise SystemExit(f"--repo-file {path!r} did not contain any repositories")
    return repos


def load_issues_from_file_or_stdin(path: str | None) -> list[dict[str, Any]]:
    if path:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        raise SystemExit("expected a JSON array of issues")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank GitHub issues for credible OSS contributions.")
    parser.add_argument("file", nargs="?", help="JSON file from gh issue list. Defaults to stdin.")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="GitHub repository to fetch directly with gh, for example owner/repo; repeat to scan multiple repos",
    )
    parser.add_argument(
        "--repo-file",
        action="append",
        default=[],
        help="newline-delimited owner/repo file to scan; blank lines and # comments are ignored",
    )
    parser.add_argument(
        "--issue-limit",
        type=int,
        default=100,
        help="number of open issues to fetch when --repo is used",
    )
    parser.add_argument(
        "--skip-fetch-errors",
        action="store_true",
        help="when scanning multiple repos, warn and continue if one repository cannot be fetched",
    )
    parser.add_argument("--limit", type=int, default=10, help="number of issues to print")
    parser.add_argument(
        "--include-label",
        action="append",
        default=[],
        help="only consider issues with this label; repeat to accept any listed label",
    )
    parser.add_argument(
        "--exclude-label",
        action="append",
        default=[],
        help="skip issues with this label before scoring; repeat for multiple labels",
    )
    parser.add_argument(
        "--require-all-labels",
        action="store_true",
        help="require every --include-label to be present instead of accepting any included label",
    )
    parser.add_argument(
        "--unassigned-only",
        action="store_true",
        help="skip issues that already have assignees before scoring",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=None,
        help="skip issues with more than this many comments before scoring",
    )
    parser.add_argument(
        "--updated-within-days",
        type=int,
        default=None,
        help="skip issues that have not been updated within this many days",
    )
    parser.add_argument(
        "--include-text",
        action="append",
        default=[],
        help="only consider issues whose title or body contains this text; repeat to accept any term",
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        choices=sorted(DOMAIN_PRESETS),
        help="append a curated include-text term set for a contribution domain; repeat to combine domains",
    )
    parser.add_argument(
        "--exclude-text",
        action="append",
        default=[],
        help="skip issues whose title or body contains this text; repeat for multiple terms",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="only print issues with this score or higher",
    )
    parser.add_argument(
        "--per-repo-limit",
        type=int,
        default=None,
        help="cap output candidates per repository after scoring, useful for balanced multi-repo scans",
    )
    parser.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown", help="output format")
    parser.add_argument(
        "--show-snippets",
        action="store_true",
        help="include compact one-line issue body previews in markdown output",
    )
    args = parser.parse_args(argv)

    if args.min_score is not None and not 0 <= args.min_score <= 100:
        raise SystemExit("--min-score must be between 0 and 100")
    if args.max_comments is not None and args.max_comments < 0:
        raise SystemExit("--max-comments must be zero or greater")
    if args.updated_within_days is not None and args.updated_within_days < 0:
        raise SystemExit("--updated-within-days must be zero or greater")
    if args.per_repo_limit is not None and args.per_repo_limit < 1:
        raise SystemExit("--per-repo-limit must be at least 1")

    repos = list(args.repo)
    for repo_file in args.repo_file:
        repos.extend(load_repos_from_file(repo_file))

    if repos and args.file:
        raise SystemExit("pass either --repo/--repo-file or a JSON file, not both")
    data = (
        load_issues_from_repos(repos, args.issue_limit, skip_fetch_errors=args.skip_fetch_errors)
        if repos
        else load_issues_from_file_or_stdin(args.file)
    )
    data = filter_issues_by_label(
        data,
        include_labels=args.include_label,
        exclude_labels=args.exclude_label,
        require_all_include_labels=args.require_all_labels,
    )
    data = filter_issues_by_workflow(
        data,
        unassigned_only=args.unassigned_only,
        max_comments=args.max_comments,
    )
    data = filter_issues_by_activity(data, updated_within_days=args.updated_within_days)
    include_text = expand_preset_terms(args.preset, args.include_text)
    data = filter_issues_by_text(data, include_terms=include_text, exclude_terms=args.exclude_text)
    ranked = limit_ranked_per_repo(filter_ranked(rank_issues(data), args.min_score), args.per_repo_limit)
    if args.format == "json":
        print(render_json(ranked, args.limit), end="")
    elif args.format == "csv":
        print(render_csv(ranked, args.limit, show_snippets=args.show_snippets), end="")
    else:
        print(render_markdown(ranked, args.limit, show_snippets=args.show_snippets), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
