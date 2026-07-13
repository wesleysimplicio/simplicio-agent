from __future__ import annotations

import json
from pathlib import Path

from tools.public_docs_audit import main, scan, to_report


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "public-docs"


def test_clean_public_docs_fixture_passes():
    findings, allowlisted, audited_files = scan(FIXTURES / "clean")
    report = to_report(findings, allowlisted, audited_files)

    assert report["audited_files"] == 1
    assert report["finding_count"] == 0
    assert report["allowlisted_count"] == 0
    assert report["schema"] == "simplicio.public-docs-audit/v1"


def test_allowlisted_migration_and_credit_lines_are_reported_but_not_failed():
    findings, allowlisted, audited_files = scan(FIXTURES / "allowlisted")
    report = to_report(findings, allowlisted, audited_files)

    assert audited_files == 2
    assert report["finding_count"] == 0
    assert report["allowlisted_count"] == 2
    assert report["allowlisted_by_class"] == {"credit": 1, "migration": 1}
    assert [item["allowlist"] for item in report["allowlisted"]] == [
        "credit-upstream-doc",
        "migration-alias-doc",
    ]


def test_allowlisted_legacy_line_still_reports_unsupported_claim():
    findings, allowlisted, audited_files = scan(FIXTURES / "allowlisted-with-claim")
    report = to_report(findings, allowlisted, audited_files)

    assert audited_files == 1
    assert report["allowlisted_count"] == 1
    assert report["allowlisted_by_class"] == {"migration": 1}
    assert report["finding_count"] == 1
    assert report["by_rule"] == {"unsupported-claim-every-mcp": 1}
    assert report["findings"][0]["path"] == "claim.md"
    assert report["findings"][0]["rule_id"] == "unsupported-claim-every-mcp"


def test_findings_cover_legacy_brand_command_and_unsupported_claims_with_evidence():
    findings, allowlisted, audited_files = scan(FIXTURES / "findings")
    report = to_report(findings, allowlisted, audited_files)

    assert audited_files == 4
    assert not allowlisted
    assert report["finding_count"] == 4
    assert report["by_rule"] == {
        "legacy-brand": 1,
        "legacy-command": 1,
        "unsupported-claim-every-mcp": 1,
        "unsupported-claim-local-llm-bundled": 1,
    }

    assert report["findings"] == [
        {
            "path": "brand-leak.md",
            "line": 1,
            "column": 1,
            "rule_id": "legacy-brand",
            "severity": "error",
            "message": "legacy Hermes branding leaked into a public doc/example",
            "evidence": "Hermes Agent ships with the public docs bundle.",
            "suggestion": "Simplicio Agent",
            "match_text": "Hermes Agent",
        },
        {
            "path": "legacy-command.md",
            "line": 1,
            "column": 6,
            "rule_id": "legacy-command",
            "severity": "error",
            "message": "legacy public command example uses a deprecated Hermes command",
            "evidence": "Run `hermes doctor` before reporting setup drift.",
            "suggestion": "simplicio-agent doctor",
            "match_text": "hermes doctor",
        },
        {
            "path": "unsupported-local-llm.md",
            "line": 1,
            "column": 13,
            "rule_id": "unsupported-claim-local-llm-bundled",
            "severity": "error",
            "message": "unsupported capability claim: 'bundles a local LLM by default'",
            "evidence": "The package bundles a local LLM by default for every install.",
            "suggestion": "describe the real optional local-model path instead of claiming a bundled default",
            "match_text": "bundles a local LLM by default",
        },
        {
            "path": "unsupported-mcp.md",
            "line": 1,
            "column": 11,
            "rule_id": "unsupported-claim-every-mcp",
            "severity": "error",
            "message": "unsupported capability claim: 'supports every MCP server'",
            "evidence": "The agent supports every MCP server without extra configuration.",
            "suggestion": "replace with the specific supported MCP transport or integration contract",
            "match_text": "supports every MCP server",
        },
    ]


def test_main_json_emits_machine_readable_report(capsys):
    exit_code = main(["--root", str(FIXTURES / "findings"), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["schema"] == "simplicio.public-docs-audit/v1"
    assert payload["finding_count"] == 4
    assert payload["audited_files"] == 4
