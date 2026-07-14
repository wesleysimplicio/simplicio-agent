"""Tests for the possibility / action gating ledger (issue #22).

Covers the four ASOLARIA economy mechanics the issue calls out:
  * 8-byte handles; bodies only when materialized,
  * tail-O(1) reuse (second mention is a cache hit, never re-paid),
  * never-explode cap (resident action budget is always respected),
  * limited recursion (delegation summaries strictly shrink),
and the core policy: possibility is cheap, action is gated and never fires
without an explicit admission, with a real (non-fabricated) cost receipt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.possibility_ledger import (
    ActionCost,
    Possibility,
    PossibilityLedger,
    assert_shrinking_delegation,
    handle_of,
)


def test_handle_is_fixed_eight_bytes_regardless_of_body_size() -> None:
    small = handle_of("a")
    large = handle_of("x" * 10_000)
    assert len(small) == 8
    assert len(large) == 8
    # deterministic and content-addressed
    assert handle_of("a") == small
    assert handle_of("b") != small


def test_possibility_is_cheap_and_body_is_lazy(tmp_path: Path) -> None:
    ledger = PossibilityLedger(max_resident_actions=4)
    calls = 0

    def body() -> str:
        nonlocal calls
        calls += 1
        return "expensive body that is never stored inline" * 50

    pos = ledger.record_possibility(
        "expensive body that is never stored inline" * 50,
        yool_id="agent.hyp",
        materializer=body,
        receipt_directory=tmp_path,
    )
    assert pos.cheap
    assert isinstance(pos, Possibility)
    # body not materialized yet
    assert calls == 0
    # handle is 8 bytes
    assert len(pos.handle) == 8
    # materialize on demand
    materialized = ledger.materialize(pos.handle)
    assert materialized == "expensive body that is never stored inline" * 50
    assert calls == 1
    assert ledger.lookup_possibility(pos.handle) is pos


def test_second_mention_is_tail_o1_cache_hit_and_never_repaid() -> None:
    ledger = PossibilityLedger(max_resident_actions=4, tail_capacity=2)
    payload = "repeated possibility body"
    first = ledger.record_possibility(payload)
    second = ledger.record_possibility(payload)
    # same handle, no duplicate storage
    assert first is second
    assert ledger.tail().count(first.handle) == 1
    # tail is bounded
    for i in range(5):
        ledger.record_possibility(f"p-{i}")
    assert len(ledger.tail()) <= 2


def test_action_is_gated_and_never_fires_without_admission() -> None:
    ledger = PossibilityLedger(max_resident_actions=2)
    cost = ActionCost(estimated_tokens=120)
    # not admitted yet -> cannot fire
    assert not ledger.is_admitted("act-1")
    with pytest.raises(RuntimeError, match="must be admitted"):
        ledger.fire_action("act-1")
    # admitted -> can fire, with real receipt
    decision = ledger.request_action("act-1", cost)
    assert decision.admitted
    assert ledger.is_admitted("act-1")
    record = ledger.fire_action("act-1")
    assert record.fired
    assert record.receipt.cost.tokens == 120
    assert record.receipt.cost.tokens > 0  # never a fabricated {tokens:0}
    assert ledger.is_fired("act-1")
    assert ledger.fired_actions == 1


def test_zero_cost_action_is_rejected_as_fabricated_receipt() -> None:
    ledger = PossibilityLedger(max_resident_actions=2)
    ledger.request_action("cheat", ActionCost(estimated_tokens=0))
    with pytest.raises(ValueError, match="real measured cost"):
        ledger.fire_action("cheat")


def test_never_explode_cap_under_adversarial_arrivals() -> None:
    ledger = PossibilityLedger(max_resident_actions=3)
    admitted = 0
    for i in range(10):  # N+k arrivals
        decision = ledger.request_action(
            f"act-{i}", ActionCost(estimated_tokens=10, resident_cost=1)
        )
        if decision.admitted:
            admitted += 1
            assert ledger.resident_actions <= 3  # invariant holds every time
    # exactly N admitted, never more
    assert admitted == 3
    assert ledger.resident_actions == 3
    # over-max-resident single action is also rejected
    big = ledger.request_action("giant", ActionCost(estimated_tokens=99, resident_cost=99))
    assert not big.admitted
    assert big.reason == "over-max-resident"


def test_completing_action_releases_resident_slot() -> None:
    ledger = PossibilityLedger(max_resident_actions=1)
    ledger.request_action("a", ActionCost(estimated_tokens=5))
    assert ledger.resident_actions == 1
    blocked = ledger.request_action("b", ActionCost(estimated_tokens=5))
    assert not blocked.admitted
    assert ledger.complete_action("a")
    assert ledger.resident_actions == 0
    assert ledger.request_action("b", ActionCost(estimated_tokens=5)).admitted


def test_shrinking_delegation_contract_rejects_non_shrinking() -> None:
    big = "word " * 100
    # equal (or larger) summary is rejected
    with pytest.raises(ValueError, match="strictly shrink"):
        assert_shrinking_delegation(big, big)
    with pytest.raises(ValueError, match="strictly shrink"):
        assert_shrinking_delegation(big, big + " extra")
    # strictly smaller summary passes with a real savings receipt
    receipt = assert_shrinking_delegation(big, "word " * 40)
    assert receipt.cost.tokens_saved > 0
    assert receipt.cost.tokens > 0


def test_ledger_records_real_cost_receipts_on_disk(tmp_path: Path) -> None:
    ledger = PossibilityLedger(max_resident_actions=4)
    ledger.record_possibility("hypothesis", receipt_directory=tmp_path)
    ledger.request_action("act", ActionCost(estimated_tokens=200))
    ledger.fire_action("act", receipt_directory=tmp_path)
    receipt_files = list(tmp_path.glob("*.json"))
    assert receipt_files, "fired action must leave a real receipt file"
    # cheap possibility receipt is honest (tokens=0), action receipt is real
    contents = [
        __import__("json").loads(p.read_text(encoding="utf-8")) for p in receipt_files
    ]
    kinds = {c["meta"]["proof_kind"] for c in contents}
    assert "cheap_possibility" in kinds
    assert "gated_action" in kinds
