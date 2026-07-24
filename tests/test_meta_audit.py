import json
import tempfile
import unittest
from pathlib import Path

from scripts.meta_audit import build_artifact, normalize_issues, render_json, render_report, main, validate_artifact


class MetaAuditTests(unittest.TestCase):
    def setUp(self):
        self.payload = [
            [
                {
                    "number": 2,
                    "title": "new issue",
                    "state": "open",
                    "created_at": "2026-01-02T00:00:00Z",
                    "updated_at": "2026-01-03T00:00:00Z",
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
                    "updated_at": "2026-01-02T00:00:00Z",
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
        self.assertIn("Audit status: **incomplete**", report)
        self.assertIn("Evidence status: **unverified by default**", report)
        self.assertNotIn("pull request", report)

    def test_markdown_and_json_reports_are_reproducible(self):
        issues = normalize_issues(self.payload)
        markdown = render_report("example/repo", issues, "snapshot:issues.json")
        json_report = render_json("example/repo", issues, "snapshot:issues.json")
        self.assertEqual(markdown, render_report("example/repo", issues, "snapshot:issues.json"))
        self.assertEqual(json_report, render_json("example/repo", issues, "snapshot:issues.json"))
        decoded = json.loads(json_report)
        self.assertEqual(decoded["summary"]["open_issue_count"], 1)
        self.assertEqual(decoded["audit"]["evidence"]["by_status"]["unverified"], 2)
        self.assertFalse(decoded["audit"]["evidence"]["complete"])

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

    def test_artifact_contract_and_offline_validator(self):
        artifact = build_artifact("example/repo", normalize_issues(self.payload), "snapshot:issues.json")
        self.assertEqual(validate_artifact(artifact), [])
        artifact["summary"]["total"] = 99
        self.assertIn("summary must equal", validate_artifact(artifact)[0])

    def test_artifact_rejects_bad_dependencies_evidence_and_open_count(self):
        artifact = build_artifact("example/repo", normalize_issues(self.payload), "snapshot:issues.json")
        artifact["issues"][0]["dependencies"] = [404]
        artifact["issues"][1]["evidence_status"] = "unknown"
        artifact["summary"]["open_issue_count"] = 99
        errors = validate_artifact(artifact)
        self.assertTrue(any("dependency references" in error for error in errors))
        self.assertTrue(any("evidence_status" in error for error in errors))
        self.assertTrue(any("summary must equal" in error for error in errors))
        artifact = build_artifact("example/repo", normalize_issues(self.payload), "snapshot:issues.json")
        artifact["audit"]["status"] = "complete"
        self.assertIn("audit.status cannot be complete while evidence is unverified or blocked", validate_artifact(artifact))

    def test_cli_writes_and_validates_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "issues.json"
            artifact = root / "inventory.json"
            snapshot.write_text(json.dumps(self.payload), encoding="utf-8")
            self.assertEqual(main(["--repo", "example/repo", "--input", str(snapshot), "--artifact", str(artifact)]), 0)
            self.assertEqual(main(["--artifact", str(artifact), "--validate", "--json"]), 0)
            json_output = root / "report.json"
            self.assertEqual(main(["--repo", "example/repo", "--input", str(snapshot), "--json", "--output", str(json_output)]), 0)
            self.assertEqual(json.loads(json_output.read_text(encoding="utf-8"))["schema"], "simplicio-agent.meta-audit-inventory/v2")


if __name__ == "__main__":
    unittest.main()
