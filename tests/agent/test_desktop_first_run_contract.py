"""Focused invariants for the bounded Desktop first-run contract."""

from __future__ import annotations

from agent.desktop_first_run_contract import (
    DEFAULT_OFF_INTEGRATIONS,
    REQUIRED_PERMISSIONS,
    BlockReason,
    DesktopFirstRunContract,
    FirstRunPolicy,
    FirstRunReceipt,
    FirstRunState,
    ModelMode,
    ReadinessStatus,
    SetupSelection,
    create_first_run_snapshot,
    evaluate_readiness,
    parse_first_run_snapshot,
    reduce_first_run,
    resume_first_run,
)


def _receipt(kind: str, *, ok: bool = True) -> FirstRunReceipt:
    return FirstRunReceipt(
        kind=kind,
        id=f"{kind}-1",
        transaction_id="tx-1",
        evidence_ref=f"evidence/{kind}",
        ok=ok,
    )


def _ready_candidate():
    state = create_first_run_snapshot("profile-1")
    state = reduce_first_run(state, {"type": "check_started"})
    state = reduce_first_run(state, {"type": "model_selected", "model": ModelMode.REMOTE})
    state = reduce_first_run(
        state,
        {
            "type": "provider_selected",
            "provider": "anthropic",
            "secret_ref": "vault://profile-1/anthropic",
        },
    )
    state = reduce_first_run(state, {"type": "workspace_selected", "workspace": "workspace-1"})
    for permission in REQUIRED_PERMISSIONS:
        state = reduce_first_run(state, {"type": "permission_granted", "permission": permission})
    for kind in ("bootstrap", "handshake", "migrations", "neural_db", "smoke"):
        state = reduce_first_run(state, {"type": "receipt", "receipt": _receipt(kind)})
    return state


def test_defaults_are_local_and_google_stripe_are_explicitly_off() -> None:
    contract = DesktopFirstRunContract()
    snapshot = contract.create("profile-1")

    assert contract.is_safe
    assert snapshot.policy.google_enabled is False
    assert snapshot.policy.stripe_enabled is False
    assert DEFAULT_OFF_INTEGRATIONS == ("google", "stripe")
    assert snapshot.state is FirstRunState.FRESH


def test_unsafe_defaults_fail_closed_before_setup_events() -> None:
    snapshot = create_first_run_snapshot(
        "profile-1",
        policy=FirstRunPolicy(google_enabled=True),
    )

    blocked = reduce_first_run(snapshot, {"type": "check_started"})

    assert blocked.state is FirstRunState.BLOCKED
    assert blocked.reason is BlockReason.UNSAFE_DEFAULTS
    assert evaluate_readiness(blocked).status is ReadinessStatus.BLOCKED
    assert not evaluate_readiness(blocked).is_ready


def test_guided_setup_requires_a_real_receipt_gated_ready_path() -> None:
    state = _ready_candidate()
    before_first_task = evaluate_readiness(state)

    assert state.state is FirstRunState.CHECKING
    assert before_first_task.is_blocked
    assert "missing_receipt:first_task" in before_first_task.blockers
    assert "state:checking" in before_first_task.blockers

    ready = reduce_first_run(state, {"type": "receipt", "receipt": _receipt("first_task")})

    assert ready.state is FirstRunState.READY
    assert ready.blocking is False
    assert ready.retryable is False
    assert evaluate_readiness(ready).status is ReadinessStatus.READY


def test_configure_later_is_navigable_degraded_but_never_ready() -> None:
    state = create_first_run_snapshot("profile-1")
    deferred = reduce_first_run(state, {"type": "setup_later"})

    decision = evaluate_readiness(deferred)

    assert deferred.state is FirstRunState.DEGRADED
    assert deferred.blocking is False
    assert deferred.reason is BlockReason.MODEL_MISSING
    assert decision.status is ReadinessStatus.DEGRADED
    assert decision.is_ready is False


def test_remote_setup_requires_a_secret_reference_not_a_raw_credential() -> None:
    state = create_first_run_snapshot("profile-1")
    state = reduce_first_run(state, {"type": "model_selected", "model": ModelMode.REMOTE})
    missing = reduce_first_run(state, {"type": "provider_selected", "provider": "anthropic"})

    assert missing.state is FirstRunState.NEEDS_PROVIDER
    assert missing.next_action == "store_provider_reference"
    assert missing.selection.secret_ref is None
    assert SetupSelection(model=ModelMode.REMOTE, provider="anthropic").is_valid is False
    assert SetupSelection(model=ModelMode.REMOTE, provider="anthropic", secret_ref="sk-live-secret").is_valid is False


def test_invalid_receipt_is_an_explicit_blocked_state() -> None:
    state = create_first_run_snapshot("profile-1")
    invalid = reduce_first_run(state, {"type": "receipt", "receipt": _receipt("smoke", ok=False)})

    assert invalid.state is FirstRunState.BLOCKED
    assert invalid.reason is BlockReason.INVALID_RECEIPT
    assert invalid.next_action == "collect_receipt"


def test_recovery_preserves_valid_receipts_and_marks_interrupted_work() -> None:
    state = _ready_candidate()
    resumed = resume_first_run(state)

    assert resumed.state is FirstRunState.CHECKING
    assert resumed.reason is BlockReason.INTERRUPTED
    assert {receipt.kind for receipt in resumed.receipts} == {
        "bootstrap",
        "handshake",
        "migrations",
        "neural_db",
        "smoke",
    }


def test_corrupt_ready_snapshot_is_repaired_not_accepted() -> None:
    state = _ready_candidate()
    ready = reduce_first_run(state, {"type": "receipt", "receipt": _receipt("first_task")})
    corrupt = ready.__class__(
        profile_id=ready.profile_id,
        state=ready.state,
        revision=ready.revision,
        selection=ready.selection,
        policy=ready.policy,
        receipts=(),
        reason=ready.reason,
        next_action=ready.next_action,
        retryable=ready.retryable,
        blocking=ready.blocking,
        transaction_id=ready.transaction_id,
    )

    repaired = resume_first_run(corrupt)

    assert repaired.state is FirstRunState.REPAIRING
    assert repaired.reason is BlockReason.CORRUPT_STATE
    assert repaired.blocking is True


def test_serialization_is_deterministic_and_parse_does_not_prove_ready() -> None:
    state = _ready_candidate()
    encoded = state.to_json()
    parsed = parse_first_run_snapshot(state.to_dict())

    assert parsed is not None
    assert encoded == state.to_json()
    assert parsed.to_dict() == state.to_dict()
    assert evaluate_readiness(parsed).is_ready is False


def test_reset_retains_policy_but_clears_only_setup_metadata() -> None:
    policy = FirstRunPolicy()
    state = create_first_run_snapshot("profile-1", policy=policy)
    state = reduce_first_run(state, {"type": "model_selected", "model": ModelMode.LOCAL})
    reset = reduce_first_run(state, {"type": "reset"})

    assert reset.profile_id == "profile-1"
    assert reset.policy == policy
    assert reset.state is FirstRunState.FRESH
    assert reset.receipts == ()
    assert reset.selection == SetupSelection()
