"""Contract tests for the issue #349 CI quality-gate wiring."""

from __future__ import annotations

import pathlib

import yaml


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".github" / "quality-gates.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "quality-gates.yml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_yaml(path: pathlib.Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain a YAML mapping"
    return value


def test_quality_gate_contract_is_deterministic() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert config["schema"] == "simplicio.ci-quality-gates/v1"
    assert config["merge_blocking"] is True
    assert config["aggregate_check"] == "quality-gates"
    assert config["required_checks"] == [
        "unit",
        "integration",
        "security",
        "cost",
        "coverage",
        "diagnostics",
    ]
    assert config["coverage"]["global_minimum_percent"] == 85
    assert config["coverage"]["critical_minimum_percent"] == 90
    assert config["cost"]["max_regression_percent"] == 20


def test_external_e2e_is_never_reported_as_available() -> None:
    e2e = _load_yaml(CONFIG_PATH)["external_e2e"]
    assert e2e["availability"] == "unavailable"
    assert e2e["status"] == "UNVERIFIED"
    assert "credentials" in e2e["reason"]


def test_quality_workflow_has_all_required_blocking_jobs() -> None:
    config = _load_yaml(CONFIG_PATH)
    workflow = _load_yaml(WORKFLOW_PATH)
    jobs = workflow["jobs"]
    required = set(config["required_checks"])
    assert required <= set(jobs)
    aggregate = jobs[config["aggregate_check"]]
    assert set(aggregate["needs"]) == required
    assert aggregate["if"] == "always()"
    assert "RESULTS" in aggregate["steps"][0]["env"]
    assert "sys.exit(1" in aggregate["steps"][0]["run"]


def test_quality_workflow_commands_are_windows_safe() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "python3" not in content
    assert "source .venv" not in content
    assert "sha256sum" not in content
    assert "continue-on-error: true" not in content
    assert "uv run ruff check" in content


def test_ci_orchestrator_runs_quality_gate_for_every_change() -> None:
    ci_jobs = _load_yaml(CI_WORKFLOW_PATH)["jobs"]
    quality_job = ci_jobs["quality-gates"]
    assert quality_job["uses"] == "./.github/workflows/quality-gates.yml"
    assert "if" not in quality_job
    assert "quality-gates" in ci_jobs["all-checks-pass"]["needs"]


def test_cost_gate_points_at_reviewed_baseline() -> None:
    config = _load_yaml(CONFIG_PATH)
    baseline = REPO_ROOT / config["cost"]["baseline"]
    baseline_doc = _load_yaml(baseline)
    assert baseline_doc["schema"] == "simplicio.perf-gate.baseline/v1"
    assert baseline_doc["threshold_pct"] == config["cost"]["max_regression_percent"]
