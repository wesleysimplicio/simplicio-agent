import json
import tempfile
import unittest
from pathlib import Path

from scripts.meta_audit import normalize_issues, render_report, main


class MetaAuditTests(unittest.TestCase):
    def setUp(self):
        self.payload = [
            [
                {
                    "number": 2,
                    "title": "new issue",
                    "state": "open",
                    "created_at": "2026-01-02T00:00:00Z",
                    "labels": [{"name": "bug"}],
                    "html_url": "https://github.com/example/repo/issues/2",
                },
                {
                    "number": 99,
                    "title": "pull request",
                    "state": "open",
                    "created_at": "2026-01-01T00:00:00Z",
                    "pull_request": {"url": "https://api.github.com/pulls/99"},
                },
            ],
            [
                {
                    "number": 1,
                    "title": "old issue",
                    "state": "closed",
                    "created_at": "2026-01-01T00:00:00Z",
                    "labels": [{"name": "docs"}, {"name": "bug"}],
                    "html_url": "https://github.com/example/repo/issues/1",
                }
            ],
        ]

    def test_normalizes_pages_excludes_prs_and_sorts(self):
        issues = normalize_issues(self.payload)
        self.assertEqual([issue["number"] for issue in issues], [1, 2])
        self.assertEqual(issues[0]["labels"], ["bug", "docs"])

    def test_report_is_deterministic_and_counts_states(self):
        issues = normalize_issues(self.payload)
        report = render_report("example/repo", issues, "snapshot:issues.json")
        self.assertEqual(report, render_report("example/repo", issues, "snapshot:issues.json"))
        self.assertIn("Total issues: **2**", report)
        self.assertIn("Open: **1**", report)
        self.assertIn("Closed: **1**", report)
        self.assertNotIn("pull request", report)

    def test_cli_uses_input_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "issues.json"
            output = root / "report.md"
            snapshot.write_text(json.dumps(self.payload), encoding="utf-8")
            self.assertEqual(
                main(["--repo", "example/repo", "--input", str(snapshot), "--output", str(output)]),
                0,
            )
            self.assertIn("snapshot:issues.json", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
