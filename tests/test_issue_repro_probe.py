"""Focused tests for the quarantine-first issue repro close gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "simplicio-loop"
    / "simplicio-tasks"
    / "scripts"
    / "issue_repro_probe.py"
)
SPEC = importlib.util.spec_from_file_location("issue_repro_probe", SCRIPT)
PROBE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROBE)


def result(command="simplicio doctor --json", **overrides):
    value = {"cmd": command, "rc": 0, "hang": False}
    value.update(overrides)
    return value


def issue(body, labels=("bug",)):
    return {"body": body, "labels": [{"name": label} for label in labels]}


def test_reported_commands_excludes_unrelated_mentions():
    body = (
        "The docs mention `simplicio status` for context.\n\n"
        "Reproduction command:\n`simplicio doctor --json`\n"
    )
    assert PROBE.extract_reported_cmds(body) == ("simplicio doctor --json",)


def test_close_gate_quarantines_without_defect_label():
    decision = PROBE.evaluate_close_gate(
        issue(
            "Reproduction command: `simplicio doctor --json`", labels=("enhancement",)
        ),
        result(),
        merged_pr=True,
        evidence=True,
    )
    assert decision.allowed is False
    assert decision.reason == "missing defect label"


def test_close_gate_quarantines_command_that_is_only_a_mention():
    decision = PROBE.evaluate_close_gate(
        issue("The docs mention `simplicio status`, but no repro is provided."),
        result(),
        merged_pr=True,
        evidence=True,
    )
    assert decision.status == "quarantined"
    assert decision.reason == "command is not the exact reported repro"


def test_close_gate_requires_delivery_and_independent_evidence():
    current = issue("Reproduction command: `simplicio doctor --json`")
    assert PROBE.evaluate_close_gate(current, result()).reason == (
        "merged delivery evidence is missing"
    )
    decision = PROBE.evaluate_close_gate(current, result(), merged_pr=True)
    assert decision.reason == "independent evidence receipt is missing"


def test_close_gate_allows_only_a_passing_exact_repro_with_full_evidence():
    decision = PROBE.evaluate_close_gate(
        issue("Reproduction command: `simplicio doctor --json`"),
        result(),
        merged_pr=True,
        evidence=True,
    )
    assert decision.to_dict() == {
        "allowed": True,
        "status": "closeable",
        "reason": "all close-gate evidence is present",
    }


def test_close_gate_quarantines_hanging_repro_even_with_other_receipts():
    decision = PROBE.evaluate_close_gate(
        issue("Reproduction command: `simplicio doctor --json`"),
        result(rc=124, hang=True),
        merged_pr=True,
        evidence=True,
    )
    assert decision.reason == "reported repro hangs"
