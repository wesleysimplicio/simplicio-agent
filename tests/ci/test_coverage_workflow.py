"""Integrity checks for the aggregated CI coverage gate."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
COVERAGE_WORKFLOW = ROOT / ".github" / "workflows" / "coverage.yml"
DOD = ROOT / "DOD.md"


def _workflow(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path} must contain a YAML mapping"
    return document


def test_coverage_workflow_is_reusable_and_enforces_the_repository_threshold():
    workflow = _workflow(COVERAGE_WORKFLOW)
    jobs = workflow["jobs"]
    coverage_job = jobs["coverage"]
    steps = coverage_job["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    triggers = workflow.get("on", workflow.get(True, {}))

    assert "workflow_call" in triggers
    assert "coverage run --rcfile=.coveragerc.core -m pytest" in commands
    assert "coverage report --rcfile=.coveragerc.core" in commands
    assert "coverage==7.8.2" in commands


def test_aggregated_gate_depends_on_coverage_job():
    workflow = _workflow(CI_WORKFLOW)
    jobs = workflow["jobs"]

    assert jobs["coverage"]["uses"] == "./.github/workflows/coverage.yml"
    assert "coverage" in jobs["all-checks-pass"]["needs"]


def test_dod_documents_the_enforced_threshold():
    dod = DOD.read_text(encoding="utf-8")

    assert ".coveragerc.core" in dod
    assert "fail_under = 85" in dod
    assert "reusable `coverage` workflow" in dod
