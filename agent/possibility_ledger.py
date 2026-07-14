"""Possibility / action gating ledger (ASOLARIA economy, issue #22).

Implements the second ASOLARIA principle for the "fast + economy" pillars:
*make possibility cheap and action gated*.

* A **possibility** (a hypothesis, a candidate plan, a speculative branch) is
  recorded by an 8-byte handle only.  Its full body is materialized lazily,
  on demand.  Re-recording the same payload is a tail-O(1) cache hit: the
  handle is already present, so nothing is re-paid.  Recording a possibility
  costs ~0 energy (the 8-byte handle).
* An **action** (a mutation / side-effecting step) is **gated**.  It is
  admitted only while the resident budget has room (never-explode cap), and
  only an admitted action may *fire*.  ``E = 0 unless explicitly fired``:
  an action never executes without an explicit gate decision, and a fired
  action is recorded with a real, measured cost receipt -- never a fabricated
  ``{tokens: 0}``.

This module is intentionally independent of the provider / tool stack so it
can be unit-tested in isolation and wired into ``conversation_loop`` and
``async_dag`` without booting a model.  It complements (does not duplicate)
``agent.token_economy``: that module owns the content-addressed artifact
registry and the shrinking summary contract; this module owns the
possibility/action *gating* policy and its append-only ledger.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from agent.model_metadata import estimate_tokens_rough
from agent.telemetry.receipts import (
    Cost,
    Receipt,
    content_hash,
    record_receipt,
)

# A possibility handle is always exactly 8 bytes (truncated content hash).
HANDLE_BYTES = 8

#: Callable that yields the (possibly large) body of a possibility on demand.
Materializer = Callable[[], str | bytes]


def handle_of(payload: str | bytes) -> bytes:
    """Derive the cheap 8-byte possibility handle from a payload.

    The body can be arbitrarily large; the handle is fixed at 8 bytes so
    recording a possibility is always fixed-cost and cheap.
    """

    return content_hash(payload).encode("utf-8")[:HANDLE_BYTES]


@dataclass(frozen=True)
class Possibility:
    """A cheap, handle-keyed hypothesis.

    The body is never stored inline -- only the 8-byte handle and a lazy
    materializer.  Possibilities are cheap by construction: recording one
    consumes a fixed 8 bytes regardless of body size.
    """

    handle: bytes
    yool_id: str
    materializer: Materializer = field(repr=False, compare=False)

    @property
    def cheap(self) -> bool:
        """A possibility is always recorded only by its 8-byte handle."""

        return len(self.handle) == HANDLE_BYTES


@dataclass(frozen=True)
class ActionCost:
    """The measured cost of a gated action.

    ``estimated_tokens`` is the real cost the action is expected to spend when
    it fires (never fabricated as 0 for a genuine mutation).  ``resident_cost``
    is how many resident slots the action occupies while live (admitted but not
    yet completed); it drives the never-explode cap.
    """

    estimated_tokens: int
    resident_cost: int = 1

    def __post_init__(self) -> None:
        if self.estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative")
        if self.resident_cost < 1:
            raise ValueError("resident_cost must be positive")


@dataclass(frozen=True)
class ActionDecision:
    """Measured result of a gate request for one action."""

    admitted: bool
    resident: int
    max_resident: int
    reason: str
    action_id: Optional[str] = None


@dataclass(frozen=True)
class ActionRecord:
    """A fired action as persisted in the ledger."""

    action_id: str
    cost: ActionCost
    receipt: Receipt
    fired: bool = True


class PossibilityLedger:
    """Append-only ledger of cheap possibilities and gated actions.

    Possibilities are stored only by their 8-byte handle.  Actions are gated
    by a resident cap (never-explode) and only recorded to the ledger once
    they actually fire, with a real measured cost receipt.
    """

    def __init__(
        self,
        *,
        max_resident_actions: int,
        tail_capacity: int = 256,
    ) -> None:
        if max_resident_actions < 1:
            raise ValueError("max_resident_actions must be positive")
        if tail_capacity < 1:
            raise ValueError("tail_capacity must be positive")
        self.max_resident_actions = max_resident_actions
        self._tail_capacity = tail_capacity
        self._possibilities: dict[bytes, Possibility] = {}
        self._tail: deque[bytes] = deque(maxlen=tail_capacity)
        self._resident_actions: dict[str, ActionCost] = {}
        self._actions: dict[str, ActionRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Possibilities: cheap, handle-keyed, lazily materialized.
    # ------------------------------------------------------------------
    def record_possibility(
        self,
        payload: str | bytes,
        *,
        yool_id: str = "agent.possibility",
        materializer: Optional[Materializer] = None,
        receipt_directory=None,
    ) -> Possibility:
        """Record a possibility by its 8-byte handle.

        Re-recording the same payload is a tail-O(1) cache hit: the handle is
        already present and the existing possibility is returned unchanged, so
        the second mention never re-pays.  A cheap possibility receipt (real
        cost 0 -- honest, not fabricated) is recorded only when
        ``receipt_directory`` is provided.
        """

        handle = handle_of(payload)
        with self._lock:
            existing = self._possibilities.get(handle)
            if existing is not None:
                return existing  # tail-O(1) reuse -- no re-pay
            if materializer is None:
                materializer = lambda p=payload: p  # type: ignore[misc]
            pos = Possibility(handle=handle, yool_id=yool_id, materializer=materializer)
            self._possibilities[handle] = pos
            self._tail.append(handle)
        if receipt_directory is not None:
            record_receipt(
                payload=payload,
                yool_id=yool_id,
                lane="fast",
                status="ok",
                tokens=0,
                tokens_raw=0,
                tokens_saved=0,
                directory=receipt_directory,
                meta={"proof_kind": "cheap_possibility", "handle": handle.hex()},
            )
        return pos

    def lookup_possibility(self, handle: bytes) -> Optional[Possibility]:
        """O(1) lookup of a possibility by its 8-byte handle."""

        return self._possibilities.get(handle)

    def materialize(self, handle: bytes) -> str | bytes:
        """Materialize the (possibly large) body of a recorded possibility."""

        pos = self._possibilities.get(handle)
        if pos is None:
            raise KeyError("unknown possibility handle")
        return pos.materializer()

    def tail(self) -> tuple[bytes, ...]:
        """Return the bounded recent-registration tail in insertion order."""

        return tuple(self._tail)

    # ------------------------------------------------------------------
    # Actions: gated, never-explode, fired only after admission.
    # ------------------------------------------------------------------
    def request_action(self, action_id: str, cost: ActionCost) -> ActionDecision:
        """Gate one action.

        Reserves a resident slot on admission (driving the never-explode cap)
        but does NOT fire it -- ``E = 0`` until :meth:`fire_action` is called.
        """

        with self._lock:
            if action_id in self._resident_actions:
                return ActionDecision(
                    True,
                    len(self._resident_actions),
                    self.max_resident_actions,
                    "already-resident",
                    action_id,
                )
            if cost.resident_cost > self.max_resident_actions:
                return ActionDecision(
                    False,
                    len(self._resident_actions),
                    self.max_resident_actions,
                    "over-max-resident",
                    action_id,
                )
            if (
                len(self._resident_actions) + cost.resident_cost
                > self.max_resident_actions
            ):
                return ActionDecision(
                    False,
                    len(self._resident_actions),
                    self.max_resident_actions,
                    "resident-budget",
                    action_id,
                )
            self._resident_actions[action_id] = cost
            return ActionDecision(
                True,
                len(self._resident_actions),
                self.max_resident_actions,
                "admitted",
                action_id,
            )

    def fire_action(
        self,
        action_id: str,
        *,
        effect: Optional[Materializer] = None,
        receipt_directory=None,
    ) -> ActionRecord:
        """Fire a previously admitted action and record it with a real receipt.

        Raises if the action was never admitted.  A fired action must carry a
        real, positive measured cost: a zero-cost "action" is a fabricated
        receipt and is rejected, honoring the never-fake-``{tokens:0}`` rule.
        """

        with self._lock:
            cost = self._resident_actions.get(action_id)
            if cost is None:
                raise RuntimeError("action must be admitted before it can fire")
            if cost.estimated_tokens <= 0:
                raise ValueError(
                    "fired actions require a real measured cost; got 0 "
                    "(use a possibility, not an action, for zero-cost hypotheses)"
                )
            payload = effect() if effect is not None else action_id
            if receipt_directory is not None:
                receipt = record_receipt(
                    payload=payload,
                    yool_id="agent.action.fired",
                    lane="fast",
                    status="ok",
                    tokens=cost.estimated_tokens,
                    tokens_raw=cost.estimated_tokens,
                    tokens_saved=0,
                    directory=receipt_directory,
                    meta={"proof_kind": "gated_action", "action_id": action_id},
                )
            else:
                sha = (
                    content_hash(payload)
                    if isinstance(payload, (str, bytes))
                    else content_hash(str(payload))
                )
                receipt = Receipt(
                    sha=sha,
                    yool_id="agent.action.fired",
                    cost=Cost(
                        tokens=cost.estimated_tokens,
                        tokens_raw=cost.estimated_tokens,
                    ),
                    meta={"proof_kind": "gated_action", "action_id": action_id},
                )
            record = ActionRecord(action_id=action_id, cost=cost, receipt=receipt)
            self._actions[action_id] = record
            return record

    def complete_action(self, action_id: str) -> bool:
        """Release the resident slot held by a fired (or admitted) action."""

        with self._lock:
            return self._resident_actions.pop(action_id, None) is not None

    def is_admitted(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._resident_actions

    def is_fired(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._actions

    @property
    def resident_actions(self) -> int:
        with self._lock:
            return len(self._resident_actions)

    @property
    def fired_actions(self) -> int:
        with self._lock:
            return len(self._actions)


def assert_shrinking_delegation(
    input_text: str,
    summary_text: str,
    *,
    receipt_directory=None,
) -> Receipt:
    """Enforce the nested-delegation shrinking contract (issue #22, scope 4).

    A sub-agent's summary must be strictly smaller than the input context it
    was derived from -- the spine-of-supervisor recursion bound that prevents
    context explosion.  Returns a real measured-savings receipt when the
    contract holds; raises ``ValueError`` otherwise.
    """

    in_tokens = estimate_tokens_rough(input_text)
    out_tokens = estimate_tokens_rough(summary_text)
    if not (0 < out_tokens < in_tokens):
        raise ValueError(
            f"delegation summary did not strictly shrink: "
            f"in={in_tokens} out={out_tokens}"
        )
    saved = in_tokens - out_tokens
    if receipt_directory is not None:
        return record_receipt(
            payload=summary_text,
            yool_id="agent.delegation.shrink",
            lane="fast",
            status="ok",
            tokens=out_tokens,
            tokens_raw=in_tokens,
            tokens_saved=saved,
            directory=receipt_directory,
            meta={"proof_kind": "shrinking_delegation"},
        )
    return Receipt(
        sha=content_hash(summary_text),
        yool_id="agent.delegation.shrink",
        cost=Cost(tokens=out_tokens, tokens_raw=in_tokens, tokens_saved=saved),
        meta={"proof_kind": "shrinking_delegation"},
    )


__all__ = [
    "HANDLE_BYTES",
    "ActionCost",
    "ActionDecision",
    "ActionRecord",
    "Possibility",
    "PossibilityLedger",
    "assert_shrinking_delegation",
    "handle_of",
]
