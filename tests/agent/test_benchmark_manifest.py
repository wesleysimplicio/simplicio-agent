import pytest

from agent.benchmark_manifest import BenchmarkTaskManifest


def test_benchmark_manifest_is_replayable_and_declares_verifier():
    manifest = BenchmarkTaskManifest(
        task_id="browser-login-smoke",
        domain="browser",
        setup="fixture:browser-login",
        goal="open the dashboard",
        constraints=("no_external_network",),
        expected_artifacts=("dashboard-screenshot",),
        verifier="artifact:dashboard-screenshot",
        timeout_s=120,
        risk_mode="read",
    )
    assert manifest.to_dict()["schema"] == "simplicio.benchmark-task/v1"
    assert len(manifest.content_hash()) == 64


def test_manifest_rejects_zero_timeout():
    with pytest.raises(ValueError, match="timeout_s"):
        BenchmarkTaskManifest("x", "browser", "setup", "goal", (), (), "verify", 0, "read")
