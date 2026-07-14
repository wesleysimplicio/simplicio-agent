"""Focused tests for the bounded rate-distortion context contract."""

import pytest

from agent.rate_distortion_context import (
    CCRReceipt,
    CCRStore,
    FidelityBudget,
    FidelityGate,
    FidelityRejected,
    canonical_json,
    score_compression,
)


def _budget(**kwargs):
    values = {"epsilon": 1.0, "max_rate": 1.0}
    values.update(kwargs)
    return FidelityBudget(**values)


def test_additive_loss_vector_and_deterministic_serialization():
    original = "AC-1 keep /srv/app.py v1.2.3; ERROR: preserve this."
    candidate = "AC-1 keep /srv/app.py v1.2.3; ERROR: preserve this. filler removed"
    first = score_compression(original, candidate)
    second = score_compression(original, candidate)

    assert first == second
    assert first.hard_failure is False
    assert first.D == pytest.approx(first.distortion)
    assert first.as_dict()["reason_codes"] == []
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


@pytest.mark.parametrize(
    "original,candidate,reason",
    [
        ("AC-1: do this", "do this", "ac_lost"),
        ("See https://example.test/a", "See the site", "url_lost"),
        ("Edit agent/file.py", "Edit the file", "path_lost"),
        ("Use `--safe-mode`", "Use the safe mode", "inline_code_lost"),
        ("```python\nreturn 1\n```", "code omitted", "fenced_code_lost"),
        ("release v1.2.3", "release v1.2.4", "number_changed"),
        ("ERROR: disk is full", "operation failed", "error_or_warning_hidden"),
        ("WARNING: retry once", "retry later", "error_or_warning_hidden"),
    ],
)
def test_load_bearing_occurrence_loss_is_hard_failure(original, candidate, reason):
    loss = score_compression(original, candidate)

    assert loss.hard_failure is True
    assert reason in loss.reason_codes
    assert loss.distortion == float("inf")


def test_safe_compression_gets_stable_ccr_and_partial_recovery():
    original = (
        "AC-1 keep this requirement.\n"
        "The explanation has removable filler words.\n"
        "See agent/file.py and ERROR: retain this warning.\n"
    )
    candidate = "AC-1 keep this requirement.\nSee agent/file.py and ERROR: retain this warning.\n"
    gate = FidelityGate(_budget(epsilon=0.5))
    result = gate.evaluate(original, candidate)

    assert result.accepted is True
    assert result.output == candidate
    assert result.receipt is not None
    receipt = result.receipt
    assert receipt.handle == CCRReceipt.from_json(receipt.to_json()).handle
    assert receipt.to_json() == CCRReceipt.from_json(receipt.to_json()).to_json()
    assert receipt.original_bytes == original.encode("utf-8")
    assert receipt.recover(start_line=1, end_line=1) == "AC-1 keep this requirement.\n"
    assert receipt.recover_by_pattern(r"ERROR") == "See agent/file.py and ERROR: retain this warning.\n"
    assert gate.store.recover(receipt.handle, pattern=r"agent/file") == (
        "See agent/file.py and ERROR: retain this warning.\n"
    )


def test_ccr_handle_is_stable_and_store_ttl_is_enforced_without_serialization_drift():
    original = "AC-1\nkeep this.\n"
    candidate = "AC-1\n"
    budget = _budget(epsilon=1.0, ttl_seconds=10)
    first = FidelityGate(budget).evaluate(original, candidate)
    second = FidelityGate(budget).evaluate(original, candidate)

    assert first.receipt is not None and second.receipt is not None
    assert first.receipt.handle == second.receipt.handle
    store = CCRStore()
    store.put(first.receipt, now=100)
    assert store.get(first.receipt.handle, now=109) is not None
    assert store.get(first.receipt.handle, now=110) is None


def test_insufficient_fidelity_fails_closed_and_preserves_original_bytes():
    original = b"AC-1: preserve bytes\xff\n"
    candidate = b"summary"
    result = FidelityGate(_budget(epsilon=100.0)).evaluate(original, candidate)

    assert result.accepted is False
    assert result.output is original
    assert result.receipt is None
    assert result.output == original
    with pytest.raises(FidelityRejected) as exc_info:
        FidelityGate(_budget(epsilon=100.0)).require(original, candidate)
    assert exc_info.value.result.reason_codes


def test_distortion_and_token_rate_budgets_reject_closed():
    original = "keep AC-1 and /tmp/file.py " + ("filler " * 40)
    candidate = original + " extra text"
    result = FidelityGate(_budget(epsilon=0.0, max_rate=0.5, token_budget=2)).evaluate(
        original, candidate
    )

    assert result.accepted is False
    assert "compression_rate_exceeded" in result.reason_codes
    assert "token_budget_exceeded" in result.reason_codes
    assert result.output == original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"epsilon": -1},
        {"epsilon": float("inf")},
        {"max_rate": 0},
        {"token_budget": 0},
        {"ttl_seconds": 0},
    ],
)
def test_budget_is_bounded(kwargs):
    with pytest.raises(ValueError):
        _budget(**kwargs)
