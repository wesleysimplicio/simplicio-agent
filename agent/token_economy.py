"""Bounded context artifacts for token-economical agent turns.

This module is deliberately adjacent to, rather than inside, prompt
construction.  A paid artifact is identified by the existing content-addressed
``Receipt.sha`` and can be admitted/materialized without changing the stable
prompt-cache prefix.  The registry is a bounded resident-token gate; its
tail is only an O(1) lookup index for recently registered artifacts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Callable

from agent.context_references import ContextReference
from agent.model_metadata import estimate_tokens_rough
from agent.telemetry.receipts import Receipt, content_hash, record_receipt

Materializer = Callable[[], str | bytes]
HANDLE_BYTES = 8


@dataclass(frozen=True)
class PaidArtifactHandle:
    """A receipt-backed artifact whose content is loaded only on demand."""

    sha: str
    handle: bytes
    label: str
    token_cost: int
    receipt: Receipt = field(repr=False, compare=False)
    materializer: Materializer = field(repr=False, compare=False)
    reference: ContextReference | None = field(default=None, compare=False)


@dataclass(frozen=True)
class AdmissionDecision:
    """Measured result of a resident-token admission attempt."""

    admitted: bool
    resident_tokens: int
    max_resident: int
    reason: str


@dataclass(frozen=True)
class MentionDecision:
    """Measured result for one context mention."""

    handle: bytes
    first: bool
    tokens: int
    reason: str


class PaidArtifactRegistry:
    """Tail-indexed registry with explicit resident-token admission.

    Registration is cheap and does not call a materializer.  A handle must be
    admitted before materialization, and materialized bytes are hash-checked
    against the receipt so a stale or adversarial loader cannot silently
    replace paid content.
    """

    def __init__(self, *, max_resident: int, tail_capacity: int = 128) -> None:
        if max_resident < 1:
            raise ValueError("max_resident must be positive")
        if tail_capacity < 1:
            raise ValueError("tail_capacity must be positive")
        self.max_resident = max_resident
        self._entries: dict[str, PaidArtifactHandle] = {}
        self._tail: deque[str] = deque(maxlen=tail_capacity)
        self._resident: set[str] = set()
        self._materialized: dict[str, str] = {}
        self._resident_tokens = 0
        self._paid: set[str] = set()
        self._lock = threading.RLock()

    @property
    def resident_tokens(self) -> int:
        """Return the measured token budget currently admitted."""

        with self._lock:
            return self._resident_tokens

    def register(
        self,
        receipt: Receipt,
        materializer: Materializer,
        *,
        label: str = "context-artifact",
        reference: ContextReference | None = None,
    ) -> PaidArtifactHandle:
        """Register a positive-cost receipt without materializing its payload."""

        if receipt.cost.tokens <= 0 or receipt.cost.tokens_raw <= 0:
            raise ValueError("paid artifacts require positive measured token cost")
        if not callable(materializer):
            raise TypeError("materializer must be callable")

        with self._lock:
            existing = self._entries.get(receipt.sha)
            if existing is not None:
                return existing

            handle = PaidArtifactHandle(
                sha=receipt.sha,
                handle=bytes.fromhex(receipt.sha)[:HANDLE_BYTES],
                label=label,
                token_cost=receipt.cost.tokens,
                receipt=receipt,
                materializer=materializer,
                reference=reference,
            )
            self._entries[handle.sha] = handle
            self._tail.append(handle.sha)
            return handle

    def lookup(self, sha: str) -> PaidArtifactHandle | None:
        """Look up a handle by content address in O(1)."""

        with self._lock:
            return self._entries.get(sha)

    def mention(self, handle_or_sha: PaidArtifactHandle | str) -> MentionDecision:
        """Record a mention without reinjecting an already-paid body."""

        with self._lock:
            handle = self._resolve(handle_or_sha)
            if handle is None:
                raise KeyError("unknown artifact")
            if handle.sha in self._paid:
                return MentionDecision(
                    handle=handle.handle,
                    first=False,
                    tokens=0,
                    reason="tail-o(1)-cache-hit",
                )
            self._paid.add(handle.sha)
            return MentionDecision(
                handle=handle.handle,
                first=True,
                tokens=handle.token_cost,
                reason="head-tax",
            )

    def admit(self, handle_or_sha: PaidArtifactHandle | str) -> AdmissionDecision:
        """Admit one handle if its measured cost fits the resident budget."""

        with self._lock:
            handle = self._resolve(handle_or_sha)
            if handle is None:
                return AdmissionDecision(
                    False, self._resident_tokens, self.max_resident, "unknown"
                )
            if handle.sha in self._resident:
                return AdmissionDecision(
                    True, self._resident_tokens, self.max_resident, "already-resident"
                )
            if handle.token_cost > self.max_resident:
                return AdmissionDecision(
                    False, self._resident_tokens, self.max_resident, "over-max-resident"
                )
            if self._resident_tokens + handle.token_cost > self.max_resident:
                return AdmissionDecision(
                    False, self._resident_tokens, self.max_resident, "resident-budget"
                )

            self._resident.add(handle.sha)
            self._resident_tokens += handle.token_cost
            return AdmissionDecision(
                True, self._resident_tokens, self.max_resident, "admitted"
            )

    def materialize(self, handle_or_sha: PaidArtifactHandle | str) -> str:
        """Materialize an admitted artifact and verify its content address."""

        with self._lock:
            handle = self._resolve(handle_or_sha)
            if handle is None:
                raise KeyError("unknown artifact")
            if handle.sha not in self._resident:
                raise RuntimeError("artifact must be admitted before materialization")
            cached = self._materialized.get(handle.sha)
            if cached is not None:
                return cached

            value = handle.materializer()
            text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
            if content_hash(text) != handle.sha:
                raise ValueError("materialized content hash does not match receipt")
            self._materialized[handle.sha] = text
            return text

    def release(self, handle_or_sha: PaidArtifactHandle | str) -> bool:
        """Release resident content and its token admission."""

        with self._lock:
            handle = self._resolve(handle_or_sha)
            if handle is None or handle.sha not in self._resident:
                return False
            self._resident.remove(handle.sha)
            self._resident_tokens -= handle.token_cost
            self._materialized.pop(handle.sha, None)
            return True

    def tail(self) -> tuple[PaidArtifactHandle, ...]:
        """Return the bounded recent-registration tail in insertion order."""

        with self._lock:
            return tuple(
                self._entries[sha] for sha in self._tail if sha in self._entries
            )

    @staticmethod
    def handle_marker(handle: PaidArtifactHandle) -> str:
        """Return the short opaque handle safe to carry in a prompt."""

        return f"⟦context:{handle.handle.hex()}⟧"

    def _resolve(
        self, handle_or_sha: PaidArtifactHandle | str
    ) -> PaidArtifactHandle | None:
        if isinstance(handle_or_sha, PaidArtifactHandle):
            return self._entries.get(handle_or_sha.sha)
        return self._entries.get(handle_or_sha)


@dataclass(frozen=True)
class ShrinkingSummary:
    """A receipt-backed summary with a strict, measurable shrinking contract."""

    text: str
    source_sha: str
    tokens: int
    level: int
    receipt: Receipt
    receipt_directory: Path | None = field(default=None, repr=False, compare=False)

    def shrink(self, max_tokens: int) -> "ShrinkingSummary":
        """Create a smaller deterministic head/tail summary.

        The source address remains stable across levels, while each summary
        receives its own content address and positive measured savings receipt.
        """

        if max_tokens < 1 or max_tokens >= self.tokens:
            raise ValueError(
                "max_tokens must be positive and smaller than current tokens"
            )
        text = _fit_text(self.text, max_tokens)
        tokens = estimate_tokens_rough(text)
        if not 0 < tokens < self.tokens:
            raise ValueError("summary did not strictly shrink")
        receipt = _summary_receipt(
            text,
            raw_tokens=self.tokens,
            source_sha=self.source_sha,
            level=self.level + 1,
            directory=self.receipt_directory,
            parent_sha=self.receipt.sha,
        )
        return ShrinkingSummary(
            text=text,
            source_sha=self.source_sha,
            tokens=tokens,
            level=self.level + 1,
            receipt=receipt,
            receipt_directory=self.receipt_directory,
        )


def make_shrinking_summary(
    text: str,
    *,
    max_tokens: int,
    receipt_directory: Path | None = None,
) -> ShrinkingSummary:
    """Create the first deterministic shrinking summary from measured text."""

    raw_tokens = estimate_tokens_rough(text)
    if raw_tokens < 2:
        raise ValueError("summary source must contain at least two measured tokens")
    if max_tokens < 1 or max_tokens >= raw_tokens:
        raise ValueError("max_tokens must be positive and smaller than source tokens")
    summary_text = _fit_text(text, max_tokens)
    tokens = estimate_tokens_rough(summary_text)
    if not 0 < tokens < raw_tokens:
        raise ValueError("summary did not strictly shrink")
    source_sha = content_hash(text)
    receipt = _summary_receipt(
        summary_text,
        raw_tokens=raw_tokens,
        source_sha=source_sha,
        level=1,
        directory=receipt_directory,
    )
    return ShrinkingSummary(
        text=summary_text,
        source_sha=source_sha,
        tokens=tokens,
        level=1,
        receipt=receipt,
        receipt_directory=receipt_directory,
    )


def register_context_artifact(
    registry: PaidArtifactRegistry,
    reference: ContextReference,
    text: str,
    *,
    receipt_directory: Path | None = None,
) -> PaidArtifactHandle:
    """Bridge an expanded ``ContextReference`` into the bounded registry."""

    tokens = estimate_tokens_rough(text)
    if tokens <= 0:
        raise ValueError("context artifact must have positive measured token cost")
    receipt = record_receipt(
        payload=text,
        yool_id="agent.context.artifact",
        lane="fast",
        status="measured",
        tokens=tokens,
        tokens_raw=tokens,
        tokens_saved=0,
        meta={
            "proof_kind": "measured_rough_estimate",
            "reference": reference.raw,
        },
        directory=receipt_directory,
    )
    return registry.register(
        receipt,
        lambda: text,
        label=reference.raw,
        reference=reference,
    )


def _summary_receipt(
    text: str,
    *,
    raw_tokens: int,
    source_sha: str,
    level: int,
    directory: Path | None,
    parent_sha: str | None = None,
) -> Receipt:
    tokens = estimate_tokens_rough(text)
    saved = raw_tokens - tokens
    if raw_tokens <= 0 or tokens <= 0 or saved <= 0:
        raise ValueError("summary receipt requires positive measured savings")
    meta = {
        "proof_kind": "measured_rough_estimate",
        "source_sha": source_sha,
        "summary_level": level,
    }
    if parent_sha is not None:
        meta["parent_sha"] = parent_sha
    return record_receipt(
        payload=text,
        yool_id="agent.context.summary",
        lane="fast",
        status="measured",
        tokens=tokens,
        tokens_raw=raw_tokens,
        tokens_saved=saved,
        meta=meta,
        directory=directory,
    )


def _fit_text(text: str, max_tokens: int) -> str:
    budget = max_tokens * 4
    if len(text) <= budget:
        return text
    marker = "\n...[summary shrunk]...\n"
    if budget <= len(marker):
        return text[:budget]
    remaining = budget - len(marker)
    head = max(1, remaining // 2)
    tail = max(1, remaining - head)
    candidate = text[:head] + marker + text[-tail:]
    while estimate_tokens_rough(candidate) > max_tokens:
        candidate = candidate[:-1]
    return candidate
