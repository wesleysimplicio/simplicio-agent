"""Failure-branch coverage for agent/golden_path.py (issue #211 gap).

The existing golden-path tests (tests/integration/test_golden_path.py) only
cover the happy path and are marked ``integration``, so a plain ``pytest``
invocation (which excludes ``-m integration`` via pyproject addopts) never
exercises them. That leaves every real failure branch in
``agent/golden_path.py`` -- mutation mismatch, unsupported fixture MCP
operation, write-set mismatch, unverified final state, rejected delivery, and
transport failure -- untested by default, which is exactly the gap the #211
quarantine reopen flagged.

These tests are intentionally NOT marked ``integration`` so they run in the
default suite. They use the real harness, the real fixture, and the real
fixture MCP transport (no mocks for the seam under test) -- only the
scenario/callable inputs are deliberately shaped to trigger each failure.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from agent.golden_path import (
    GoldenPathError,
    GoldenPathHarness,
    GoldenPathScenario,
    _apply_mutation,
    build_fixture_mcp_call,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "golden-path"


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "golden-path"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def test_apply_mutation_raises_when_before_content_does_not_match(tmp_path):
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)
    # Corrupt the on-disk content so it no longer matches expected_before.
    scenario.mutation_path.write_text("status=corrupted\n", encoding="utf-8")

    with pytest.raises(GoldenPathError, match="unexpected pre-edit content"):
        _apply_mutation(scenario)


def test_fixture_mcp_call_raises_for_unsupported_operation(tmp_path):
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)
    call = build_fixture_mcp_call(scenario)

    with pytest.raises(GoldenPathError, match="unsupported fixture MCP operation"):
        call("not_a_real_operation", {})


def test_harness_raises_when_transport_step_fails(tmp_path):
    """A failing transport step (line via _require_ok) surfaces as GoldenPathError."""
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)

    def _broken_mcp_call(operation: str, args: dict[str, Any]) -> Any:
        if operation == "orient":
            raise RuntimeError("simulated transport outage")
        return build_fixture_mcp_call(scenario)(operation, args)

    harness = GoldenPathHarness(
        scenario,
        cli_bin=str(fixture_root / "missing-simplicio"),
        mcp_call=_broken_mcp_call,
    )

    with pytest.raises(GoldenPathError, match=r"orient failed via mcp"):
        harness.run()


def test_harness_raises_on_write_set_mismatch(tmp_path):
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)

    def _wrong_write_set_mcp_call(operation: str, args: dict[str, Any]) -> Any:
        if operation == "mechanical_edit":
            result = build_fixture_mcp_call(scenario)(operation, args)
            result["files_modified"] = [str(fixture_root / "not-the-write-set.txt")]
            return result
        return build_fixture_mcp_call(scenario)(operation, args)

    harness = GoldenPathHarness(
        scenario,
        cli_bin=str(fixture_root / "missing-simplicio"),
        mcp_call=_wrong_write_set_mcp_call,
    )

    with pytest.raises(GoldenPathError, match="write_set mismatch"):
        harness.run()


def test_harness_raises_when_final_state_does_not_match_after_validation(tmp_path):
    """A gate that rubber-stamps 'allow' without checking real content must
    still be caught by the independent post-validation requery."""
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)

    def _lying_mcp_call(operation: str, args: dict[str, Any]) -> Any:
        base = build_fixture_mcp_call(scenario)
        if operation == "mechanical_edit":
            # Apply a mutation that diverges from the expected final state,
            # while still reporting the correct write-set as modified.
            target = scenario.mutation_path
            target.write_text("status=wrong\nversion=999\n", encoding="utf-8")
            return {
                "applied": True,
                "files_modified": [str(target)],
                "write_set": [str(path) for path in scenario.absolute_write_set],
            }
        if operation == "gate":
            # Rubber-stamp validation regardless of actual disk content.
            return {
                "decision": "allow",
                "target": str(scenario.mutation_path),
                "matches_expected": True,
                "observed": "status=wrong\nversion=999\n",
                "expected": scenario.mutation.expected_after,
                "command": args["command"],
            }
        return base(operation, args)

    harness = GoldenPathHarness(
        scenario,
        cli_bin=str(fixture_root / "missing-simplicio"),
        mcp_call=_lying_mcp_call,
    )

    with pytest.raises(
        GoldenPathError, match="did not produce a verified final state"
    ):
        harness.run()


def test_harness_raises_when_delivery_is_not_accepted(tmp_path):
    fixture_root = _copy_fixture(tmp_path)
    scenario = GoldenPathScenario.from_path(fixture_root)

    def _rejected_delivery_mcp_call(operation: str, args: dict[str, Any]) -> Any:
        if operation == "ledger":
            return {"accepted": False, "event": args["event"]}
        return build_fixture_mcp_call(scenario)(operation, args)

    harness = GoldenPathHarness(
        scenario,
        cli_bin=str(fixture_root / "missing-simplicio"),
        mcp_call=_rejected_delivery_mcp_call,
    )

    with pytest.raises(GoldenPathError, match="delivery acknowledgment was not accepted"):
        harness.run()
