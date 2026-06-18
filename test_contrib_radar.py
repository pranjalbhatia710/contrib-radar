import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from contrib_radar import (
    filter_issues_by_activity,
    filter_issues_by_label,
    filter_issues_by_workflow,
    filter_ranked,
    load_issues_from_gh,
    main,
    rank_issue,
    rank_issues,
    render_json,
    render_markdown,
)

NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


class ContribRadarTests(unittest.TestCase):
    def test_good_first_issue_scores_high(self):
        issue = {
            "number": 7,
            "title": "Fix docs typo in install guide",
            "body": "Small typo in the quickstart.",
            "labels": [{"name": "good first issue"}, {"name": "documentation"}],
            "comments": 0,
            "updatedAt": "2026-06-01T00:00:00Z",
            "url": "https://example.test/7",
        }
        ranked = rank_issue(issue, now=NOW)
        self.assertGreaterEqual(ranked.score, 90)
        self.assertIn("good first issue", ranked.labels)
        self.assertTrue(any("concrete" in reason for reason in ranked.reasons))

    def test_assigned_broad_stale_issue_is_penalized(self):
        issue = {
            "number": 10,
            "title": "Architecture rewrite tracking issue",
            "body": "Umbrella roadmap for a migration.",
            "labels": [{"name": "stale"}],
            "comments": 22,
            "assignees": [{"login": "maintainer"}],
            "updatedAt": "2024-01-01T00:00:00Z",
        }
        ranked = rank_issue(issue, now=NOW)
        self.assertLess(ranked.score, 20)
        self.assertTrue(any("assigned" in reason for reason in ranked.reasons))

    def test_rank_issues_sorts_by_score_descending(self):
        issues = [
            {"number": 2, "title": "Roadmap epic", "labels": [{"name": "stale"}], "comments": 20},
            {"number": 1, "title": "Add regression test", "labels": [{"name": "help wanted"}], "comments": 1},
        ]
        ranked = rank_issues(issues)
        self.assertEqual([issue.number for issue in ranked], [1, 2])

    def test_render_markdown_includes_scores_and_urls(self):
        ranked = [rank_issue({"number": 3, "title": "Fix crash", "url": "https://example.test/3"}, now=NOW)]
        output = render_markdown(ranked, limit=1)
        self.assertIn("# contrib-radar results", output)
        self.assertIn("#3", output)
        self.assertIn("https://example.test/3", output)

    def test_render_json_outputs_machine_readable_scores(self):
        ranked = [rank_issue({"number": 3, "title": "Fix crash", "url": "https://example.test/3"}, now=NOW)]
        output = render_json(ranked, limit=1)
        self.assertIn('"score"', output)
        self.assertIn('"number": 3', output)

    def test_filter_ranked_applies_minimum_score(self):
        ranked = [
            rank_issue(
                {"number": 1, "title": "Fix crash", "labels": [{"name": "good first issue"}, {"name": "bug"}], "comments": 0},
                now=NOW,
            ),
            rank_issue({"number": 2, "title": "Roadmap epic", "labels": [{"name": "stale"}]}, now=NOW),
        ]

        filtered = filter_ranked(ranked, min_score=80)

        self.assertEqual([issue.number for issue in filtered], [1])

    def test_filter_issues_by_label_includes_any_requested_label(self):
        issues = [
            {"number": 1, "labels": [{"name": "bug"}]},
            {"number": 2, "labels": [{"name": "documentation"}]},
            {"number": 3, "labels": [{"name": "question"}]},
        ]

        filtered = filter_issues_by_label(issues, include_labels=["BUG", "feature"])

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_filter_issues_by_label_matches_common_aliases(self):
        issues = [
            {"number": 1, "labels": [{"name": "documentation"}]},
            {"number": 2, "labels": [{"name": "good-first-issue"}]},
            {"number": 3, "labels": [{"name": "help wanted"}]},
            {"number": 4, "labels": [{"name": "bug"}]},
        ]

        filtered = filter_issues_by_label(
            issues,
            include_labels=["docs", "good first issue", "help-wanted"],
        )

        self.assertEqual([issue["number"] for issue in filtered], [1, 2, 3])

    def test_filter_issues_by_label_exclude_wins_over_include(self):
        issues = [
            {"number": 1, "labels": [{"name": "good first issue"}]},
            {"number": 2, "labels": [{"name": "good first issue"}, {"name": "blocked"}]},
        ]

        filtered = filter_issues_by_label(
            issues,
            include_labels=["good first issue"],
            exclude_labels=["blocked"],
        )

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_filter_issues_by_workflow_skips_assigned_and_comment_churn(self):
        issues = [
            {"number": 1, "comments": 2, "assignees": []},
            {"number": 2, "comments": 1, "assignees": [{"login": "maintainer"}]},
            {"number": 3, "comments": 7, "assignees": []},
        ]

        filtered = filter_issues_by_workflow(issues, unassigned_only=True, max_comments=3)

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_filter_issues_by_activity_skips_stale_and_missing_timestamps(self):
        issues = [
            {"number": 1, "updatedAt": "2026-06-01T00:00:00Z"},
            {"number": 2, "updatedAt": "2026-05-01T00:00:00Z"},
            {"number": 3},
        ]

        filtered = filter_issues_by_activity(issues, updated_within_days=14, now=NOW)

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_main_rejects_invalid_min_score(self):
        with self.assertRaisesRegex(SystemExit, "--min-score must be between 0 and 100"):
            main(["--min-score", "101"])

    def test_main_rejects_invalid_max_comments(self):
        with self.assertRaisesRegex(SystemExit, "--max-comments must be zero or greater"):
            main(["--max-comments", "-1"])

    def test_main_rejects_invalid_updated_within_days(self):
        with self.assertRaisesRegex(SystemExit, "--updated-within-days must be zero or greater"):
            main(["--updated-within-days", "-1"])

    def test_main_filters_json_output_by_min_score(self):
        issues = [
            {"number": 1, "title": "Fix crash", "labels": [{"name": "good first issue"}, {"name": "bug"}], "comments": 0},
            {"number": 2, "title": "Roadmap epic", "labels": [{"name": "stale"}], "comments": 20},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--min-score", "80"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])

    def test_main_applies_label_filters_before_scoring(self):
        issues = [
            {"number": 1, "title": "Fix crash", "labels": [{"name": "bug"}], "comments": 0},
            {"number": 2, "title": "Fix flaky test", "labels": [{"name": "bug"}, {"name": "blocked"}], "comments": 0},
            {"number": 3, "title": "Document setup", "labels": [{"name": "documentation"}], "comments": 0},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--include-label", "bug", "--exclude-label", "blocked"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])

    def test_main_applies_workflow_filters_before_scoring(self):
        issues = [
            {"number": 1, "title": "Fix crash", "labels": [{"name": "bug"}], "comments": 1, "assignees": []},
            {
                "number": 2,
                "title": "Fix assigned crash",
                "labels": [{"name": "bug"}],
                "comments": 1,
                "assignees": [{"login": "maintainer"}],
            },
            {"number": 3, "title": "Fix debated crash", "labels": [{"name": "bug"}], "comments": 9, "assignees": []},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--unassigned-only", "--max-comments", "3"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])

    def test_main_applies_activity_filter_before_scoring(self):
        issues = [
            {"number": 1, "title": "Fix current crash", "updatedAt": "2026-06-03T00:00:00Z"},
            {"number": 2, "title": "Fix old crash", "updatedAt": "2025-06-03T00:00:00Z"},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout), patch(
            "contrib_radar.datetime"
        ) as fake_datetime:
            fake_datetime.now.return_value = NOW
            fake_datetime.fromisoformat = datetime.fromisoformat
            exit_code = main(["--format", "json", "--updated-within-days", "30"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])

    def test_load_issues_from_gh_invokes_issue_list(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps([{"number": 9, "title": "Fix docs"}]),
            stderr="",
        )

        with patch("subprocess.run", return_value=completed) as run:
            issues = load_issues_from_gh("owner/repo", 25)

        self.assertEqual(issues, [{"number": 9, "title": "Fix docs"}])
        command = run.call_args.args[0]
        self.assertIn("owner/repo", command)
        self.assertIn("25", command)
        self.assertIn("number,title,body,labels,comments,assignees,updatedAt,url", command)

    def test_load_issues_from_gh_reports_cli_errors(self):
        error = subprocess.CalledProcessError(1, ["gh"], stderr="not found")

        with patch("subprocess.run", side_effect=error), self.assertRaisesRegex(
            SystemExit, "gh issue list failed: not found"
        ):
            load_issues_from_gh("owner/repo", 10)

    def test_main_rejects_repo_and_file_together(self):
        with self.assertRaisesRegex(SystemExit, "pass either --repo or a JSON file"):
            main(["issues.json", "--repo", "owner/repo"])


if __name__ == "__main__":
    unittest.main()
