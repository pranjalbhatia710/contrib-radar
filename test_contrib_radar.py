import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from contrib_radar import (
    expand_preset_terms,
    filter_issues_by_activity,
    filter_issues_by_label,
    filter_issues_by_text,
    filter_issues_by_workflow,
    filter_ranked,
    limit_ranked_per_repo,
    load_issues_from_gh,
    load_issues_from_repos,
    load_repos_from_file,
    main,
    rank_issue,
    rank_issues,
    render_csv,
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

    def test_rank_issue_scores_label_aliases(self):
        issue = {
            "number": 8,
            "title": "Document setup error",
            "body": "Add missing setup troubleshooting docs.",
            "labels": [{"name": "help-wanted"}, {"name": "doc"}],
            "comments": 0,
            "updatedAt": "2026-06-01T00:00:00Z",
        }

        ranked = rank_issue(issue, now=NOW)

        self.assertGreaterEqual(ranked.score, 90)
        self.assertIn("+14 label:help-wanted", ranked.reasons)
        self.assertIn("+8 label:doc", ranked.reasons)

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

    def test_render_markdown_can_include_body_snippets(self):
        ranked = [
            rank_issue(
                {
                    "number": 4,
                    "title": "Document install error",
                    "body": "First line.\n\nSecond line with setup context.",
                    "url": "https://example.test/4",
                },
                now=NOW,
            )
        ]

        without_snippet = render_markdown(ranked, limit=1)
        with_snippet = render_markdown(ranked, limit=1, show_snippets=True)

        self.assertNotIn("Snippet:", without_snippet)
        self.assertIn("Snippet: First line. Second line with setup context.", with_snippet)

    def test_render_json_outputs_machine_readable_scores(self):
        ranked = [rank_issue({"number": 3, "title": "Fix crash", "url": "https://example.test/3"}, now=NOW)]
        output = render_json(ranked, limit=1)
        self.assertIn('"score"', output)
        self.assertIn('"number": 3', output)

    def test_render_csv_outputs_spreadsheet_friendly_rows(self):
        ranked = [
            rank_issue(
                {
                    "number": 3,
                    "title": "Fix crash, then document it",
                    "url": "https://example.test/3",
                    "repository": "owner/repo",
                    "labels": [{"name": "bug"}, {"name": "help wanted"}],
                    "body": "Reproducer and expected behavior.",
                },
                now=NOW,
            )
        ]

        output = render_csv(ranked, limit=1, show_snippets=True)

        self.assertIn("score,number,title,url,repository,labels,reasons,body_snippet", output)
        self.assertIn('"Fix crash, then document it"', output)
        self.assertIn("owner/repo", output)
        self.assertIn("bug; help wanted", output)
        self.assertIn("Reproducer and expected behavior.", output)

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

    def test_limit_ranked_per_repo_keeps_balanced_global_order(self):
        ranked = [
            rank_issue({"number": 1, "title": "Fix crash", "repository": "owner/one"}, now=NOW),
            rank_issue({"number": 2, "title": "Fix docs", "repository": "owner/one"}, now=NOW),
            rank_issue({"number": 3, "title": "Fix test", "repository": "owner/two"}, now=NOW),
            rank_issue({"number": 4, "title": "Fix install", "repository": "owner/two"}, now=NOW),
        ]

        limited = limit_ranked_per_repo(ranked, per_repo_limit=1)

        self.assertEqual(
            [(issue.repository, issue.number) for issue in limited],
            [("owner/one", 1), ("owner/two", 3)],
        )

    def test_limit_ranked_per_repo_noop_without_limit(self):
        ranked = [rank_issue({"number": 1, "title": "Fix crash", "repository": "owner/one"}, now=NOW)]

        self.assertEqual(limit_ranked_per_repo(ranked), ranked)

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

    def test_filter_issues_by_label_can_require_all_included_labels(self):
        issues = [
            {"number": 1, "labels": [{"name": "bug"}, {"name": "help wanted"}]},
            {"number": 2, "labels": [{"name": "bug"}]},
            {"number": 3, "labels": [{"name": "help wanted"}]},
            {"number": 4, "labels": [{"name": "Bug"}, {"name": "help-wanted"}]},
        ]

        filtered = filter_issues_by_label(
            issues,
            include_labels=["bug", "help wanted"],
            require_all_include_labels=True,
        )

        self.assertEqual([issue["number"] for issue in filtered], [1, 4])

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

    def test_filter_issues_by_workflow_accepts_gh_comment_nodes(self):
        issues = [
            {"number": 1, "comments": [{"body": "one"}, {"body": "two"}], "assignees": []},
            {"number": 2, "comments": [{"body": "one"}, {"body": "two"}, {"body": "three"}], "assignees": []},
        ]

        filtered = filter_issues_by_workflow(issues, max_comments=2)

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_rank_issue_counts_gh_comment_nodes(self):
        issue = {"number": 1, "title": "Fix crash", "comments": [{"body": "one"}, {"body": "two"}]}

        ranked = rank_issue(issue, now=NOW)

        self.assertTrue(any("small discussion" in reason for reason in ranked.reasons))

    def test_filter_issues_by_activity_skips_stale_and_missing_timestamps(self):
        issues = [
            {"number": 1, "updatedAt": "2026-06-01T00:00:00Z"},
            {"number": 2, "updatedAt": "2026-05-01T00:00:00Z"},
            {"number": 3},
        ]

        filtered = filter_issues_by_activity(issues, updated_within_days=14, now=NOW)

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_activity_filter_accepts_naive_imported_timestamps(self):
        issues = [
            {"number": 1, "updatedAt": "2026-06-01T00:00:00"},
            {"number": 2, "updated_at": "2026-05-01T00:00:00"},
        ]

        filtered = filter_issues_by_activity(issues, updated_within_days=14, now=NOW)

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_rank_issue_accepts_naive_imported_timestamp(self):
        issue = {"number": 1, "title": "Fix crash", "updatedAt": "2026-06-01T00:00:00"}

        ranked = rank_issue(issue, now=NOW)

        self.assertTrue(any("recently active" in reason for reason in ranked.reasons))

    def test_filter_issues_by_text_includes_title_or_body_matches(self):
        issues = [
            {"number": 1, "title": "Fix CAD export", "body": ""},
            {"number": 2, "title": "Docs", "body": "Agent setup is unclear."},
            {"number": 3, "title": "Improve billing page", "body": ""},
        ]

        filtered = filter_issues_by_text(issues, include_terms=["cad", "agent"])

        self.assertEqual([issue["number"] for issue in filtered], [1, 2])

    def test_filter_issues_by_text_exclude_wins_over_include(self):
        issues = [
            {"number": 1, "title": "Fix robotics dataset", "body": "Small bug."},
            {"number": 2, "title": "Fix robotics API", "body": "Breaking change proposal."},
        ]

        filtered = filter_issues_by_text(
            issues,
            include_terms=["robotics"],
            exclude_terms=["breaking change"],
        )

        self.assertEqual([issue["number"] for issue in filtered], [1])

    def test_expand_preset_terms_appends_domain_terms(self):
        terms = expand_preset_terms(["cad", "ai-agents"], ["docs"])

        self.assertEqual(terms[0], "docs")
        self.assertIn("workplane", terms)
        self.assertIn("mcp", terms)

    def test_expand_preset_terms_rejects_unknown_presets(self):
        with self.assertRaisesRegex(SystemExit, "unknown --preset"):
            expand_preset_terms(["unknown-domain"])

    def test_main_applies_preset_terms_before_scoring(self):
        issues = [
            {"number": 1, "title": "Fix Workplane export", "body": "Small CAD issue."},
            {"number": 2, "title": "Fix billing chart", "body": "Small failure."},
        ]

        from io import StringIO

        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--preset", "cad"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [1])

    def test_main_rejects_invalid_min_score(self):
        with self.assertRaisesRegex(SystemExit, "--min-score must be between 0 and 100"):
            main(["--min-score", "101"])

    def test_main_rejects_invalid_max_comments(self):
        with self.assertRaisesRegex(SystemExit, "--max-comments must be zero or greater"):
            main(["--max-comments", "-1"])

    def test_main_rejects_invalid_updated_within_days(self):
        with self.assertRaisesRegex(SystemExit, "--updated-within-days must be zero or greater"):
            main(["--updated-within-days", "-1"])

    def test_main_rejects_invalid_per_repo_limit(self):
        with self.assertRaisesRegex(SystemExit, "--per-repo-limit must be at least 1"):
            main(["--per-repo-limit", "0"])

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

    def test_main_can_render_csv_output(self):
        issues = [
            {"number": 1, "title": "Fix crash", "url": "https://example.test/1", "comments": 0},
        ]

        from io import StringIO

        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "csv"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(stdout.getvalue().startswith("score,number,title,url,repository,labels,reasons\r\n"))
        self.assertIn("Fix crash", stdout.getvalue())

    def test_main_caps_json_output_per_repo(self):
        issues = [
            {"number": 1, "title": "Fix crash", "repository": "owner/one", "comments": 0},
            {"number": 2, "title": "Fix docs", "repository": "owner/one", "comments": 0},
            {"number": 3, "title": "Fix test", "repository": "owner/two", "comments": 0},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--per-repo-limit", "1"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            [(issue["repository"], issue["number"]) for issue in payload],
            [("owner/one", 1), ("owner/two", 3)],
        )

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

    def test_main_can_require_all_include_labels(self):
        issues = [
            {"number": 1, "title": "Fix crash", "labels": [{"name": "bug"}], "comments": 0},
            {"number": 2, "title": "Fix wanted crash", "labels": [{"name": "bug"}, {"name": "help wanted"}], "comments": 0},
            {"number": 3, "title": "Improve help wanted docs", "labels": [{"name": "help-wanted"}], "comments": 0},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main([
                "--format",
                "json",
                "--include-label",
                "bug",
                "--include-label",
                "help wanted",
                "--require-all-labels",
            ])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["number"] for issue in payload], [2])

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

    def test_main_applies_text_filters_before_scoring(self):
        issues = [
            {"number": 1, "title": "Fix agent trace export", "body": "Small failure."},
            {"number": 2, "title": "Fix agent migration", "body": "Breaking change discussion."},
            {"number": 3, "title": "Fix billing chart", "body": "Small failure."},
        ]

        from io import StringIO
        stdout = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(issues))), patch("sys.stdout", stdout):
            exit_code = main(
                [
                    "--format",
                    "json",
                    "--include-text",
                    "agent",
                    "--exclude-text",
                    "breaking change",
                ]
            )

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

    def test_load_issues_from_repos_fetches_each_repo_and_tags_source(self):
        def fake_load(repo, issue_limit):
            return [{"number": issue_limit, "title": f"Fix {repo}"}]

        with patch("contrib_radar.load_issues_from_gh", side_effect=fake_load) as load:
            issues = load_issues_from_repos(["owner/one", "owner/two"], 25)

        self.assertEqual([call.args for call in load.call_args_list], [("owner/one", 25), ("owner/two", 25)])
        self.assertEqual([issue["repository"] for issue in issues], ["owner/one", "owner/two"])

    def test_load_issues_from_repos_preserves_existing_repository_field(self):
        with patch(
            "contrib_radar.load_issues_from_gh",
            return_value=[{"number": 1, "repository": "api/source"}],
        ):
            issues = load_issues_from_repos(["owner/repo"], 10)

        self.assertEqual(issues[0]["repository"], "api/source")

    def test_load_issues_from_repos_names_failing_repo(self):
        with patch("contrib_radar.load_issues_from_gh", side_effect=SystemExit("boom")):
            with self.assertRaisesRegex(SystemExit, "owner/repo: boom"):
                load_issues_from_repos(["owner/repo"], 10)

    def test_load_issues_from_repos_can_skip_fetch_errors(self):
        def fake_load(repo, issue_limit):
            if repo == "owner/broken":
                raise SystemExit("not found")
            return [{"number": issue_limit, "title": f"Fix {repo}"}]

        from io import StringIO

        stderr = StringIO()
        with patch("contrib_radar.load_issues_from_gh", side_effect=fake_load), patch("sys.stderr", stderr):
            issues = load_issues_from_repos(["owner/broken", "owner/good"], 10, skip_fetch_errors=True)

        self.assertEqual([issue["repository"] for issue in issues], ["owner/good"])
        self.assertIn("warning: skipped owner/broken: not found", stderr.getvalue())

    def test_load_issues_from_repos_errors_when_all_skipped(self):
        with patch("contrib_radar.load_issues_from_gh", side_effect=SystemExit("boom")):
            with self.assertRaisesRegex(SystemExit, "all repository fetches failed"):
                load_issues_from_repos(["owner/broken"], 10, skip_fetch_errors=True)

    def test_load_issues_from_repos_rejects_blank_repo_values(self):
        with self.assertRaisesRegex(SystemExit, "at least one non-empty --repo"):
            load_issues_from_repos(["  "], 10)

    def test_load_repos_from_file_ignores_comments_and_blank_lines(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("# daily targets\n\nowner/one\nowner/two  # inline note\n")
            handle.flush()

            repos = load_repos_from_file(handle.name)

        self.assertEqual(repos, ["owner/one", "owner/two"])

    def test_load_repos_from_file_rejects_invalid_entries(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("owner-only\n")
            handle.flush()

            with self.assertRaisesRegex(SystemExit, "expected owner/repo"):
                load_repos_from_file(handle.name)

    def test_main_accepts_repeated_repo_flags(self):
        def fake_load(repo, issue_limit):
            return [{"number": 1 if repo.endswith("one") else 2, "title": f"Fix {repo}", "comments": 0}]

        from io import StringIO

        stdout = StringIO()
        with patch("contrib_radar.load_issues_from_gh", side_effect=fake_load), patch("sys.stdout", stdout):
            exit_code = main(["--format", "json", "--repo", "owner/one", "--repo", "owner/two"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual({issue["repository"] for issue in payload}, {"owner/one", "owner/two"})

    def test_main_can_skip_repo_fetch_errors(self):
        def fake_load(repo, issue_limit):
            if repo.endswith("broken"):
                raise SystemExit("rate limited")
            return [{"number": 2, "title": "Fix good repo", "comments": 0}]

        from io import StringIO

        stdout = StringIO()
        stderr = StringIO()
        with patch("contrib_radar.load_issues_from_gh", side_effect=fake_load), patch("sys.stdout", stdout), patch(
            "sys.stderr", stderr
        ):
            exit_code = main(
                [
                    "--format",
                    "json",
                    "--skip-fetch-errors",
                    "--repo",
                    "owner/broken",
                    "--repo",
                    "owner/good",
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([issue["repository"] for issue in payload], ["owner/good"])
        self.assertIn("warning: skipped owner/broken: rate limited", stderr.getvalue())

    def test_main_accepts_repo_file_targets(self):
        def fake_load(repo, issue_limit):
            return [{"number": 1 if repo.endswith("one") else 2, "title": f"Fix {repo}", "comments": 0}]

        from io import StringIO

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("owner/one\nowner/two\n")
            handle.flush()
            stdout = StringIO()
            with patch("contrib_radar.load_issues_from_gh", side_effect=fake_load), patch("sys.stdout", stdout):
                exit_code = main(["--format", "json", "--repo-file", handle.name])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual({issue["repository"] for issue in payload}, {"owner/one", "owner/two"})

    def test_main_rejects_repo_and_file_together(self):
        with self.assertRaisesRegex(SystemExit, "pass either --repo/--repo-file or a JSON file"):
            main(["issues.json", "--repo", "owner/repo"])


if __name__ == "__main__":
    unittest.main()
