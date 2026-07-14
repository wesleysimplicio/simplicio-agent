"""Focused contracts for the bounded #340 equivalence/canary slice."""

from __future__ import annotations

import json

from tools.equivalence_gate import (
    EQUIVALENCE_SCHEMA,
    CanaryController,
    FeatureFlagStore,
    evaluate_shadow_reports,
)


def shadow(
    *,
    category: str = "routine",
    latency: float = 100,
    candidate_latency: float | None = None,
    behavior: object = None,
    candidate_behavior: object = None,
    memory: int = 1000,
    candidate_memory: int | None = None,
    tokens: int = 100,
    candidate_tokens: int | None = None,
    receipts: object = None,
    candidate_receipts: object = None,
) -> dict:
    candidate_latency = latency if candidate_latency is None else candidate_latency
    candidate_memory = memory if candidate_memory is None else candidate_memory
    candidate_tokens = tokens if candidate_tokens is None else candidate_tokens
    behavior = (
        {"effect_request": {"action": "read"}, "output": "ok"}
        if behavior is None
        else behavior
    )
    candidate_behavior = behavior if candidate_behavior is None else candidate_behavior
    receipts = (
        {"schema": "simplicio.effect-receipt/v1", "required_fields": ["id", "status"]}
        if receipts is None
        else receipts
    )
    candidate_receipts = receipts if candidate_receipts is None else candidate_receipts
    return {
        "schema": "simplicio.shadow-report/v1",
        "fixture_id": f"fixture-{category}",
        "category": category,
        "baseline": {
            "behavior": behavior,
            "tokens": tokens,
            "latency": {"p95": latency},
            "memory": {"peak_memory_bytes": memory},
            "receipts": receipts,
        },
        "candidate": {
            "behavior": candidate_behavior,
            "tokens": candidate_tokens,
            "latency": {"p95": candidate_latency},
            "memory": {"peak_memory_bytes": candidate_memory},
            "receipts": candidate_receipts,
        },
    }


def test_all_dimensions_at_tolerance_promote_and_aggregate_by_category() -> None:
    result = evaluate_shadow_reports([
        shadow(
            category="routine",
            latency=100,
            candidate_latency=110,
            memory=1000,
            candidate_memory=1100,
        ),
        shadow(category="routine"),
    ])
    assert result["schema"] == EQUIVALENCE_SCHEMA
    assert result["verdict"] == "promote"
    assert result["categories"]["routine"]["sample_count"] == 2


def test_behavior_difference_rejects_with_fixture_and_effect_reason() -> None:
    result = evaluate_shadow_reports([
        shadow(
            candidate_behavior={"effect_request": {"action": "write"}, "output": "ok"}
        )
    ])
    assert result["verdict"] == "reject"
    reason = next(
        reason for reason in result["reasons"] if reason["dimension"] == "behavior"
    )
    assert reason["fixture_id"] == "fixture-routine"
    assert reason["code"] == "dimension_out_of_tolerance"


def test_latency_observation_can_hold_while_blocking_dimensions_pass() -> None:
    result = evaluate_shadow_reports(
        [shadow(candidate_latency=125)],
        tolerances={"latency": {"limit": 0.10, "severity": "observation"}},
    )
    assert result["verdict"] == "hold"
    assert result["reasons"][0]["severity"] == "observation"


def test_receipt_schema_and_required_fields_are_strict() -> None:
    changed = {
        "schema": "simplicio.other-receipt/v1",
        "required_fields": ["id", "status"],
    }
    result = evaluate_shadow_reports([shadow(candidate_receipts=changed)])
    assert result["verdict"] == "reject"
    assert any(reason["dimension"] == "receipts" for reason in result["reasons"])


def test_missing_or_corrupt_reports_reject_fail_closed() -> None:
    assert evaluate_shadow_reports([])["verdict"] == "reject"
    assert evaluate_shadow_reports([{}])["verdict"] == "reject"
    assert (
        evaluate_shadow_reports([{"schema": "not-a-shadow-report"}])["verdict"]
        == "reject"
    )


def test_flag_missing_corrupt_and_profile_session_mismatch_stay_off(tmp_path) -> None:
    store = FeatureFlagStore(tmp_path)
    assert not store.is_enabled(
        "native.slice.demo", profile_id="internal", session_id="s1"
    )
    store.path.write_text("{not-json", encoding="utf-8")
    assert not store.is_enabled("demo", profile_id="internal", session_id="s1")
    store.set_enabled("demo", profile_id="internal", session_id="s1", enabled=True)
    assert store.is_enabled("demo", profile_id="internal", session_id="s1")
    assert not store.is_enabled("demo", profile_id="other", session_id="s1")
    assert not store.is_enabled("demo", profile_id="internal", session_id="s2")


def test_canary_journals_activation_and_auto_rollback(tmp_path) -> None:
    store = FeatureFlagStore(tmp_path / "state")
    controller = CanaryController(store, tmp_path / "journal.jsonl", "demo")
    assert controller.activate("internal", "session-1")
    assert store.is_enabled("demo", profile_id="internal", session_id="session-1")
    assert controller.rollback_on_divergence(
        "internal", "session-1", divergence_rate=0.11, threshold=0.10
    )
    assert not store.is_enabled("demo", profile_id="internal", session_id="session-1")
    events = [
        json.loads(line)
        for line in (tmp_path / "journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["enabled"] for event in events] == [True, False]
    assert all(
        event["profile_id"] == "internal" and event["session_id"] == "session-1"
        for event in events
    )
