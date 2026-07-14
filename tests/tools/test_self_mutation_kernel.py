"""Focused contracts for the composed #315 self-mutation boundary."""

from pathlib import Path

from tools.shadow_effects import EffectKind, EffectRequest
from tools.self_mutation_kernel import SelfMutationKernel
from tools.transaction_primitives import snapshot_tree


def _tree(root: Path, value: str) -> None:
    root.mkdir()
    (root / "app.txt").write_text(value, encoding="utf-8")


def _report(*, candidate_value: str = "same") -> dict:
    behavior = {"output": "ok", "value": "same"}
    candidate_behavior = {"output": "ok", "value": candidate_value}
    receipt = {
        "schema": "simplicio.effect-receipt/v1",
        "required_fields": ["id", "status"],
    }
    return {
        "schema": "simplicio.shadow-report/v1",
        "fixture_id": "kernel-fixture",
        "category": "routine",
        "baseline": {
            "behavior": behavior,
            "tokens": 10,
            "latency": {"p95": 10},
            "memory": {"peak_memory_bytes": 100},
            "receipts": receipt,
        },
        "candidate": {
            "behavior": candidate_behavior,
            "tokens": 10,
            "latency": {"p95": 10},
            "memory": {"peak_memory_bytes": 100},
            "receipts": receipt,
        },
    }


def _runner(candidate: Path, interceptor) -> dict:
    del candidate
    read = EffectRequest(EffectKind.FS_READ, "read", "app.txt")
    write = EffectRequest(
        EffectKind.FS_WRITE,
        "write",
        payload={"path": "shadow.txt", "content": "shadow-only"},
    )
    network = EffectRequest(EffectKind.NETWORK_HTTP, "GET", "https://example.invalid")
    interceptor.intercept(read, read_through=lambda _: "ok")
    interceptor.intercept(write)
    interceptor.intercept(network)
    return {
        "equivalence_report": _report(),
        "legacy_effects": [read, write, network],
        "shadow_effects": [read, write, network],
    }


def test_equivalent_shadow_promotes_and_keeps_canary_exactly_scoped(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _tree(baseline, "before")
    _tree(candidate, "after")
    candidate_digest = snapshot_tree(candidate).snapshot_id
    kernel = SelfMutationKernel(tmp_path / "state")

    receipt = kernel.apply(
        baseline,
        candidate,
        shadow_runner=_runner,
        profile_id="internal",
        session_id="session-1",
        promoted_commit="commit-1",
        fencing_token=1,
        health_check=lambda context: {
            "healthy": True,
            "commit": "commit-1",
            "digest": candidate_digest,
            "smoke": True,
        },
    )

    assert receipt.status == "committed"
    assert receipt.snapshot_before == snapshot_tree(baseline).snapshot_id
    assert receipt.snapshot_after == candidate_digest
    assert receipt.rollback_to is None
    assert receipt.canary_enabled
    assert (baseline / "app.txt").read_text(encoding="utf-8") == "before"
    assert kernel.promotion.current() == candidate_digest
    assert kernel.canary.store.is_enabled(
        "self-mutation", profile_id="internal", session_id="session-1"
    )
    assert not kernel.canary.store.is_enabled(
        "self-mutation", profile_id="internal", session_id="session-2"
    )
    assert kernel.journal.records()[0].mutation is not None


def test_non_equivalent_shadow_never_promotes_or_activates_canary(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _tree(baseline, "before")
    _tree(candidate, "after")
    kernel = SelfMutationKernel(tmp_path / "state")

    def runner(path, interceptor):
        del path, interceptor
        return {"equivalence_report": _report(candidate_value="diverged")}

    receipt = kernel.apply(
        baseline,
        candidate,
        shadow_runner=runner,
        profile_id="internal",
        session_id="session-1",
        promoted_commit="commit-1",
        fencing_token=1,
        health_check=lambda _: (_ for _ in ()).throw(AssertionError("not called")),
    )

    assert receipt.status == "rejected"
    assert receipt.equivalence_verdict == "reject"
    assert kernel.promotion.current() == snapshot_tree(baseline).snapshot_id
    assert not kernel.canary.store.is_enabled(
        "self-mutation", profile_id="internal", session_id="session-1"
    )


def test_health_failure_rolls_back_pointer_and_canary(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _tree(baseline, "before")
    _tree(candidate, "after")
    candidate_digest = snapshot_tree(candidate).snapshot_id
    kernel = SelfMutationKernel(tmp_path / "state")

    receipt = kernel.apply(
        baseline,
        candidate,
        shadow_runner=_runner,
        profile_id="internal",
        session_id="session-1",
        promoted_commit="commit-1",
        fencing_token=1,
        health_check=lambda _: {
            "healthy": False,
            "commit": "commit-1",
            "digest": candidate_digest,
            "reason": "smoke failed",
        },
    )

    baseline_digest = snapshot_tree(baseline).snapshot_id
    assert receipt.status == "rolled_back"
    assert receipt.snapshot_before == baseline_digest
    assert receipt.snapshot_after == candidate_digest
    assert receipt.rollback_to == baseline_digest
    assert kernel.promotion.current() == baseline_digest
    assert not kernel.canary.store.is_enabled(
        "self-mutation", profile_id="internal", session_id="session-1"
    )


def test_shadow_runner_failure_is_rejected_without_touching_baseline(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _tree(baseline, "before")
    _tree(candidate, "after")
    kernel = SelfMutationKernel(tmp_path / "state")

    receipt = kernel.apply(
        baseline,
        candidate,
        shadow_runner=lambda *_: (_ for _ in ()).throw(RuntimeError("injected")),
        profile_id="internal",
        session_id="session-1",
        promoted_commit="commit-1",
        fencing_token=1,
        health_check=lambda _: {"healthy": True},
    )

    assert receipt.status == "rejected"
    assert receipt.snapshot_before == snapshot_tree(baseline).snapshot_id
    assert kernel.promotion.current() == receipt.snapshot_before
    assert (baseline / "app.txt").read_text(encoding="utf-8") == "before"
