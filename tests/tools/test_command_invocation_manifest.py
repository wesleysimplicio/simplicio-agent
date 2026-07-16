"""Focused contract tests for the agent_tool manifest slice (issue #398)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.command_invocation_manifest import (
    CLASS_NAME,
    CLASSIFIED_STAGES,
    REPO_ROOT,
    REACHABILITY_PROBE_TOOL,
    RUNTIME_EVIDENCE_STAGES,
    RUNTIME_UNKNOWN_STAGES,
    SCHEMA,
    STAGES,
    generate_manifest,
    main,
    probe_runtime_reachability,
    validate_manifest,
)


def test_manifest_covers_the_live_registry() -> None:
    # NOTE: axis membership is NOT asserted against a second, independent
    # registry read. Several check_fns probe live external state (docker,
    # network, MCP/plugin toolsets such as Spotify attach on a background
    # timer) that can grow the registry within a process lifetime — unlike
    # the source-only perf_integration_manifest, this reflects live registry
    # state, not just repo content. A single generate_manifest() call is
    # internally consistent because it reads the registry exactly once.
    document = generate_manifest(REPO_ROOT)
    assert document["schema"] == SCHEMA
    assert document["version"] == 1
    assert document["scope"]["class"] == CLASS_NAME
    assert len(document["axes"]) > 0

    names = [axis["name"] for axis in document["axes"]]
    assert len(names) == len(set(names))
    for axis in document["axes"]:
        if axis["stage_status"]["REGISTERED"] == "pass":
            assert axis["toolset"]
            assert axis["source_path"]
            assert axis["symbol"]
            assert axis["registry"] == "tools.registry"
            assert isinstance(axis["requires_env"], list)
            assert isinstance(axis["has_authorization_gate"], bool)


def test_every_axis_classifies_all_stages_but_only_asserts_the_classified_ones() -> None:
    document = generate_manifest(REPO_ROOT)
    runtime_probe = document["runtime_reachability"]
    for axis in document["axes"]:
        assert set(axis["stage_status"]) == set(STAGES)
        assert axis["class"] == CLASS_NAME
        for stage in STAGES:
            if stage not in CLASSIFIED_STAGES:
                if (
                    axis["name"] == runtime_probe["tool"]
                    and stage in RUNTIME_EVIDENCE_STAGES
                ):
                    assert axis["stage_status"][stage] == runtime_probe["stage_status"][stage]
                else:
                    assert axis["stage_status"][stage] == "unknown"
        expected_ok = all(
            axis["stage_status"][s] == "pass" for s in CLASSIFIED_STAGES
        )
        assert axis["classified_ok"] == expected_ok


def test_unknown_tool_fails_declared_and_downstream_classified_stages() -> None:
    from tools.command_invocation_manifest import _classify_tool

    result = _classify_tool("__definitely_not_a_registered_tool__").as_dict()
    assert result["stage_status"]["DECLARED"] == "fail"
    assert result["stage_status"]["REGISTERED"] == "fail"
    assert result["classified_ok"] is False


def test_validator_rejects_bad_schema() -> None:
    document = generate_manifest(REPO_ROOT)
    document["schema"] = "wrong/v0"
    errors = validate_manifest(document)
    assert any("schema" in error for error in errors)


def test_validator_accepts_generated_manifest() -> None:
    document = generate_manifest(REPO_ROOT)
    assert validate_manifest(document) == []


def test_validator_reports_structural_manifest_errors() -> None:
    invalid_axis_statuses = {stage: "invalid" for stage in STAGES}
    invalid_runtime_statuses = {
        stage: "invalid"
        for stage in RUNTIME_EVIDENCE_STAGES + RUNTIME_UNKNOWN_STAGES
    }
    errors = validate_manifest(
        {
            "schema": "wrong/v0",
            "version": 0,
            "generator": "wrong.py",
            "axes": [
                {"class": "wrong", "stage_status": invalid_axis_statuses},
                {"class": "wrong", "stage_status": invalid_axis_statuses},
                "not-an-object",
            ],
            "summary": {"axis_count": 99},
            "runtime_reachability": {
                "tool": "",
                "stage_status": invalid_runtime_statuses,
            },
        }
    )

    assert any("schema" in error for error in errors)
    assert any("axis names must be unique" in error for error in errors)
    assert any("invalid status value" in error for error in errors)
    assert any("tool must be a non-empty string" in error for error in errors)
    assert validate_manifest({"axes": "not-a-list"})
    missing_runtime_errors = validate_manifest({"axes": [], "summary": {"axis_count": 0}})
    assert any("runtime_reachability must be an object" in error for error in missing_runtime_errors)


def test_cli_validate_reports_missing_and_invalid_files(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.json"
    assert main(["--validate", str(missing)]) == 2
    assert "invalid manifest" in capsys.readouterr().err

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["--validate", str(invalid)]) == 1
    assert "schema must" in capsys.readouterr().err


def test_runtime_reachability_probe_uses_live_registry_and_pipeline() -> None:
    probe = probe_runtime_reachability()

    assert probe["tool"] == REACHABILITY_PROBE_TOOL
    assert probe["status"] == "pass"
    assert probe["invocation_count"] == 1
    assert probe["receipt_written"] is True
    assert probe["stage_status"]["ROUTED"] == "pass"
    assert probe["stage_status"]["INVOKED"] == "pass"
    assert probe["stage_status"]["RESULT_NORMALIZED"] == "pass"
    assert probe["stage_status"]["EVIDENCED"] == "pass"
    assert probe["stage_status"]["E2E_PROVEN"] == "unknown"
    assert probe["result_sha256"]


def test_runtime_reachability_fails_closed_for_unknown_tool() -> None:
    probe = probe_runtime_reachability("__definitely_not_a_registered_tool__")

    assert probe["status"] == "fail"
    assert probe["invocation_count"] == 0
    assert probe["stage_status"]["ROUTED"] == "fail"
    assert all(
        status != "pass" for status in probe["stage_status"].values()
    )


def test_generated_manifest_attaches_probe_evidence_only_to_probed_axis() -> None:
    document = generate_manifest(REPO_ROOT)
    probe = document["runtime_reachability"]
    axis = next(axis for axis in document["axes"] if axis["name"] == probe["tool"])

    assert axis["stage_status"]["INVOKED"] == probe["stage_status"]["INVOKED"]
    assert axis["stage_status"]["EVIDENCED"] == probe["stage_status"]["EVIDENCED"]
    other_axes = [axis for axis in document["axes"] if axis["name"] != probe["tool"]]
    assert other_axes
    assert all(axis["stage_status"]["INVOKED"] == "unknown" for axis in other_axes)


def test_cli_json_output_round_trips(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    rc = main(["--generate", str(output)])
    assert rc in (0, 1)  # some tools may legitimately be gated off in this env
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema"] == SCHEMA
    assert validate_manifest(document) == []


def test_cli_validate_subcommand(tmp_path: Path, capsys) -> None:
    output = tmp_path / "manifest.json"
    main(["--generate", str(output)])
    rc = main(["--validate", str(output)])
    assert rc == 0
    assert "valid" in capsys.readouterr().out
