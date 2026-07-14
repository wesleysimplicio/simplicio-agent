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
    assert config["receipts"] == {
        "required": True,
        "format": "junit-xml",
        "retention_days": 14,
        "missing_status": "UNVERIFIED",
    }
    assert config["cost"]["metrics"] == ["latency", "model_cost_policy"]


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
    evaluate = next(
        step
        for step in aggregate["steps"]
        if step.get("name") == "Evaluate required gate results"
    )
    assert "RESULTS" in evaluate["env"]
    assert "sys.exit(1" in evaluate["run"]
    assert "quality-gates-summary.json" in _step_text(aggregate)


def _step_text(job: dict) -> str:
    """Return executable workflow text for a job, including multiline runs."""

    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps", [])
        if isinstance(step, dict)
    )


def test_required_gates_are_bounded_and_publish_execution_receipts() -> None:
    config = _load_yaml(CONFIG_PATH)
    workflow = _load_yaml(WORKFLOW_PATH)
    for gate in config["required_checks"]:
        job = workflow["jobs"][gate]
        assert isinstance(job["timeout-minutes"], int)
        assert job["timeout-minutes"] > 0
        command_text = _step_text(job)
        assert f"quality-gate-{gate}.xml" in command_text
        assert any(
            step.get("uses", "").startswith("actions/upload-artifact@")
            and f"quality-gate-{gate}.xml" in str(step.get("with", {}).get("path", ""))
            for step in job["steps"]
            if isinstance(step, dict)
        )


def test_integration_and_security_cover_contract_and_authority_boundaries() -> None:
    workflow = _load_yaml(WORKFLOW_PATH)
    integration = _step_text(workflow["jobs"]["integration"])
    security = _step_text(workflow["jobs"]["security"])
    assert "tests/tools/test_benchmark_gate.py" in integration
    assert "tests/agent/distributed/test_protocol.py" in security
    assert "tests/agent/test_trust_boundary.py" in security
    assert "tests/agent/test_autonomy_policy.py" in security


def test_cost_gate_runs_policy_and_baseline_comparison_with_receipts() -> None:
    workflow = _load_yaml(WORKFLOW_PATH)
    cost = _step_text(workflow["jobs"]["cost"])
    assert "tests/tools/test_perf_gate.py" in cost
    assert "tools.perf_gate.compare" in cost
    assert "quality-gates-cost-report.json" in cost
    assert "status':'UNVERIFIED'" in cost


def test_coverage_uses_reviewed_config_and_explicit_global_threshold() -> None:
    workflow = _load_yaml(WORKFLOW_PATH)
    coverage = _step_text(workflow["jobs"]["coverage"])
    assert "--cov-config=.coveragerc" in coverage
    assert "--cov-fail-under=85" in coverage
    config_text = (REPO_ROOT / ".coveragerc").read_text(encoding="utf-8")
    assert "branch = true" in config_text
    assert "fail_under = 85" in config_text


def test_quality_workflow_commands_are_windows_safe() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "python3" not in content
    assert "source .venv" not in content
    assert "sha256sum" not in content
    assert "continue-on-error: true" not in content
    assert "uv run ruff check" in content
    diagnostics = _load_yaml(WORKFLOW_PATH)["jobs"]["diagnostics"]
    assert diagnostics["defaults"]["run"]["shell"] == "pwsh"
    assert "uv run pytest tests/ci" in _step_text(diagnostics)


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
