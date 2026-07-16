"""Focused contract tests for the agent_tool manifest slice (issue #398)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.command_invocation_manifest import (
    CLASS_NAME,
    CLASSIFIED_STAGES,
    REPO_ROOT,
    SCHEMA,
    STAGES,
    generate_manifest,
    main,
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


def test_every_axis_classifies_all_stages_but_only_asserts_the_classified_ones() -> None:
    document = generate_manifest(REPO_ROOT)
    for axis in document["axes"]:
        assert set(axis["stage_status"]) == set(STAGES)
        assert axis["class"] == CLASS_NAME
        for stage in STAGES:
            if stage not in CLASSIFIED_STAGES:
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
