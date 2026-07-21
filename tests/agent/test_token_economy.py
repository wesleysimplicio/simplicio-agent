from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent.context_references import ContextReference
from agent.model_metadata import estimate_tokens_rough
from agent.telemetry.receipts import Cost, Receipt, content_hash
from agent.token_economy import (
    ContextEmission,
    PaidArtifactRegistry,
    ShrinkingSummary,
    make_shrinking_summary,
    register_context_artifact,
)


def _reference() -> ContextReference:
    return ContextReference(
        raw="@file:notes.txt",
        kind="file",
        target="notes.txt",
        start=0,
        end=15,
    )


def _receipt(text: str, *, tokens: int | None = None) -> Receipt:
    measured = tokens if tokens is not None else estimate_tokens_rough(text)
    return Receipt(
        sha=content_hash(text),
        cost=Cost(tokens=measured, tokens_raw=measured),
    )


def test_registry_is_lazy_deduplicated_and_hash_checked(tmp_path: Path) -> None:
    text = "a" * 80
    calls = 0

    def load() -> str:
        nonlocal calls
        calls += 1
        return text

    registry = PaidArtifactRegistry(max_resident=30, tail_capacity=1)
    handle = register_context_artifact(
        registry, _reference(), text, receipt_directory=tmp_path
    )
    duplicate = registry.register(_receipt(text), load, label="duplicate")

    assert handle is duplicate
    assert calls == 0
    assert registry.lookup(handle.sha) is handle
    assert registry.admit(handle).admitted
    assert registry.materialize(handle) == text
    assert registry.materialize(handle) == text
    assert calls == 0  # the bridge's original lazy value is cached in the registry

    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert data["cost"]["tokens"] > 0
    assert data["meta"]["proof_kind"] == "measured_rough_estimate"


def test_registry_rejects_zero_cost_and_does_not_materialize() -> None:
    registry = PaidArtifactRegistry(max_resident=10)
    receipt = Receipt(sha=content_hash("paid"), cost=Cost(tokens=0, tokens_raw=0))
    with pytest.raises(ValueError, match="positive measured token cost"):
        registry.register(receipt, lambda: "paid")


def test_admission_is_bounded_before_loader_and_release_reclaims_budget() -> None:
    first = "first artifact" * 4
    second = "second artifact" * 4
    calls = 0

    def blocked_loader() -> str:
        nonlocal calls
        calls += 1
        return second

    registry = PaidArtifactRegistry(
        max_resident=max(estimate_tokens_rough(first), estimate_tokens_rough(second))
    )
    first_handle = registry.register(_receipt(first), lambda: first)
    second_handle = registry.register(_receipt(second), blocked_loader)

    assert registry.admit(first_handle).admitted
    decision = registry.admit(second_handle)
    assert not decision.admitted
    assert decision.reason == "resident-budget"
    assert calls == 0
    assert registry.materialize(first_handle) == first
    assert registry.release(first_handle)
    assert registry.resident_tokens == 0
    assert registry.admit(second_handle).admitted


def test_registry_rejects_stale_or_adversarial_materializer() -> None:
    registry = PaidArtifactRegistry(max_resident=10)
    handle = registry.register(_receipt("trusted"), lambda: "tampered")
    assert registry.admit(handle).admitted
    with pytest.raises(ValueError, match="content hash"):
        registry.materialize(handle)


def test_render_emits_body_once_then_a_handle_with_measured_savings() -> None:
    text = "paid context body " * 20
    calls = 0

    def load() -> str:
        nonlocal calls
        calls += 1
        return text

    registry = PaidArtifactRegistry(max_resident=100)
    handle = registry.register(_receipt(text), load)

    first = registry.render(handle)
    second = registry.render(handle)

    assert isinstance(first, ContextEmission)
    assert first.text == text
    assert not first.cache_hit
    assert first.admitted
    assert second.text == second.handle == registry.handle(handle)
    assert second.cache_hit
    assert second.tokens_saved > 0
    assert calls == 1
    assert registry.resident_tokens <= registry.max_resident


def test_expand_handle_materializes_only_after_explicit_admission() -> None:
    text = "explicitly expandable context body " * 10
    calls = 0

    def load() -> str:
        nonlocal calls
        calls += 1
        return text

    registry = PaidArtifactRegistry(max_resident=100)
    handle = registry.register(_receipt(text), load)
    opaque = registry.handle(handle)

    with pytest.raises(RuntimeError, match="admitted"):
        registry.expand(opaque)
    assert calls == 0

    assert registry.admit(handle).admitted
    assert registry.expand(opaque) == text
    assert registry.expand(opaque) == text
    assert calls == 1


def test_short_handle_collision_is_rejected_before_ambiguous_expansion() -> None:
    registry = PaidArtifactRegistry(max_resident=10)
    first = Receipt(
        sha="00" * 8 + "11" * 24,
        cost=Cost(tokens=1, tokens_raw=1),
    )
    second = Receipt(
        sha="00" * 8 + "22" * 24,
        cost=Cost(tokens=1, tokens_raw=1),
    )

    registry.register(first, lambda: "first")
    with pytest.raises(ValueError, match="ambiguous context handle collision"):
        registry.register(second, lambda: "second")


def test_tail_is_bounded_and_lookup_remains_content_addressed() -> None:
    registry = PaidArtifactRegistry(max_resident=100, tail_capacity=2)
    handles = [
        registry.register(_receipt(f"artifact-{i}"), lambda i=i: f"artifact-{i}")
        for i in range(3)
    ]

    assert [handle.label for handle in registry.tail()] == [
        "context-artifact",
        "context-artifact",
    ]
    assert registry.lookup(handles[0].sha) is handles[0]
    assert registry.lookup(handles[2].sha) is handles[2]


def test_handle_is_short_but_full_sha_remains_collision_safe() -> None:
    text = "short handle with a full content address"
    registry = PaidArtifactRegistry(max_resident=100)
    handle = registry.register(_receipt(text), lambda: text)

    assert len(handle.handle) == 8
    assert handle.handle == bytes.fromhex(handle.sha)[:8]
    assert len(handle.sha) == 64


def test_second_mention_is_a_zero_token_tail_cache_hit() -> None:
    text = "the same paid context artifact"
    registry = PaidArtifactRegistry(max_resident=100)
    handle = registry.register(_receipt(text), lambda: text)

    first = registry.mention(handle)
    second = registry.mention(handle)

    assert first.first
    assert first.tokens == handle.token_cost
    assert not second.first
    assert second.tokens == 0
    assert second.reason == "tail-o(1)-cache-hit"


def test_concurrent_admission_never_exceeds_resident_cap() -> None:
    registry = PaidArtifactRegistry(max_resident=8)
    handles = [
        registry.register(_receipt(f"concurrent-{i}", tokens=1), lambda i=i: f"concurrent-{i}")
        for i in range(64)
    ]

    with ThreadPoolExecutor(max_workers=16) as pool:
        decisions = list(pool.map(registry.admit, handles))

    assert sum(decision.admitted for decision in decisions) == 8
    assert registry.resident_tokens == 8


def test_summary_contract_shrinks_with_positive_measured_receipt(
    tmp_path: Path,
) -> None:
    source = "header\n" + ("important middle detail\n" * 80) + "tail"
    summary = make_shrinking_summary(
        source,
        max_tokens=estimate_tokens_rough(source) // 2,
        receipt_directory=tmp_path,
    )
    smaller = summary.shrink(max_tokens=summary.tokens // 2)

    assert isinstance(summary, ShrinkingSummary)
    assert summary.source_sha == smaller.source_sha == content_hash(source)
    assert 0 < smaller.tokens < summary.tokens < estimate_tokens_rough(source)
    assert smaller.level == summary.level + 1
    assert smaller.receipt.cost.tokens > 0
    assert smaller.receipt.cost.tokens_raw == summary.tokens
    assert smaller.receipt.cost.tokens_saved == summary.tokens - smaller.tokens
    assert smaller.receipt.meta["proof_kind"] == "measured_rough_estimate"


def test_summary_rejects_non_shrinking_or_empty_inputs() -> None:
    with pytest.raises(ValueError, match="at least two"):
        make_shrinking_summary("tiny", max_tokens=1)
    with pytest.raises(ValueError, match="smaller"):
        source = "four words here now"
        make_shrinking_summary(source, max_tokens=estimate_tokens_rough(source))
