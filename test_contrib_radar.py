import unittest
from datetime import datetime, timezone

from contrib_radar import rank_issue, rank_issues, render_markdown

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


if __name__ == "__main__":
    unittest.main()
