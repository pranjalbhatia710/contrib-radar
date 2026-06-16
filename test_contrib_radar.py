import json
import unittest
from datetime import datetime, timezone

from contrib_radar import filter_ranked, main, rank_issue, rank_issues, render_json, render_markdown

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

    def test_main_rejects_invalid_min_score(self):
        with self.assertRaisesRegex(SystemExit, "--min-score must be between 0 and 100"):
            main(["--min-score", "101"])

    def test_main_filters_json_output_by_min_score(self):
        issues = [
            {"number": 1, "title": "Fix crash", "labels": [{"name": "good first issue"}, {"name": "bug"}], "comments": 0},
            {"number": 2, "title": "Roadmap epic", "labels": [{"name": "stale"}], "comments": 20},
        ]

        from io import StringIO
        from unittest.mock import patch

        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--min-score", "80"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])


if __name__ == "__main__":
    unittest.main()
