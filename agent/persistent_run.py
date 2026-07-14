"""Durable, transport-free persistent-run contract (issue #155).

This module describes the state that a run may carry across a process restart.
It deliberately does not start workers, call providers, or perform cleanup: a
caller owns those effects and records their receipts here.  Unknown effects
therefore remain visible and prevent an honest completed state.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping


PERSISTENT_RUN_SCHEMA = "simplicio.persistent-run"
PERSISTENT_RUN_SCHEMA_VERSION = "simplicio.persistent-run/v1"


class RunState(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class RunEffectStatus(StrEnum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    UNKNOWN = "unknown"
    RECONCILED = "reconciled"


class PersistentRunError(ValueError):
    """Base error for malformed or unsafe run state."""


class InvalidRunTransition(PersistentRunError):
    """Raised when a lifecycle transition is not allowed."""


class DuplicateCommittedEffect(PersistentRunError):
    """Raised when a committed effect would be applied twice."""


class CompletionNotReady(PersistentRunError):
    """Raised when a run tries to complete without enough proof."""


_TERMINAL = frozenset({RunState.CANCELLED, RunState.COMPLETED, RunState.FAILED})
_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.PLANNED: frozenset({RunState.QUEUED, RunState.CANCELLED}),
    RunState.QUEUED: frozenset({
        RunState.RUNNING,
        RunState.PAUSED,
        RunState.BLOCKED,
        RunState.CANCELLED,
    }),
    RunState.RUNNING: frozenset({
        RunState.WAITING_HUMAN,
        RunState.BLOCKED,
        RunState.PAUSED,
        RunState.CANCELLING,
        RunState.COMPLETED,
        RunState.FAILED,
    }),
    RunState.WAITING_HUMAN: frozenset({
        RunState.RUNNING,
        RunState.BLOCKED,
        RunState.PAUSED,
        RunState.CANCELLED,
    }),
    RunState.BLOCKED: frozenset({
        RunState.QUEUED,
        RunState.PAUSED,
        RunState.CANCELLED,
        RunState.FAILED,
    }),
    RunState.PAUSED: frozenset({RunState.QUEUED, RunState.CANCELLED}),
    RunState.CANCELLING: frozenset({RunState.CANCELLED, RunState.FAILED}),
}
_SENSITIVE = frozenset({"secret", "token", "password", "credential", "api_key"})


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise PersistentRunError(f"{field} must be non-empty")
    return result


def _pairs(
    value: Mapping[str, Any] | tuple[tuple[str, Any], ...],
    field: str,
    *,
    reject_sensitive: bool = False,
) -> tuple[tuple[str, Any], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    result: list[tuple[str, Any]] = []
    for key, item in items:
        key = _text(key, f"{field} key")
        if reject_sensitive and any(part in key.casefold() for part in _SENSITIVE):
            raise PersistentRunError(f"{field} cannot persist sensitive key {key!r}")
        if isinstance(item, (dict, list, set, tuple)):
            raise PersistentRunError(f"{field} values must be scalar")
        if not isinstance(item, (str, int, float, bool)) and item is not None:
            raise PersistentRunError(f"{field} values must be JSON scalars")
        result.append((key, item))
    result.sort(key=lambda pair: pair[0])
    if len({key for key, _ in result}) != len(result):
        raise PersistentRunError(f"{field} must not contain duplicate keys")
    return tuple(result)


def _refs(value: tuple[str, ...] | list[str], field: str) -> tuple[str, ...]:
    result = tuple(_text(item, field) for item in value)
    if len(set(result)) != len(result):
        raise PersistentRunError(f"{field} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class RunEffect:
    """One idempotent effect boundary recorded by a persistent run."""

    effect_id: str
    idempotency_key: str
    status: RunEffectStatus = RunEffectStatus.PREPARED
    receipt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _text(self.effect_id, "effect_id"))
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "idempotency_key")
        )
        if not isinstance(self.status, RunEffectStatus):
            object.__setattr__(self, "status", RunEffectStatus(self.status))
        if self.receipt:
            object.__setattr__(self, "receipt", _text(self.receipt, "receipt"))

    def to_dict(self) -> dict[str, str]:
        return {
            "effect_id": self.effect_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status.value,
            "receipt": self.receipt,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunEffect":
        return cls(
            effect_id=data["effect_id"],
            idempotency_key=data["idempotency_key"],
            status=data.get("status", RunEffectStatus.PREPARED),
            receipt=data.get("receipt", ""),
        )


@dataclass(frozen=True, slots=True)
class PersistentRun:
    """Versioned run envelope that can be serialized and resumed safely."""

    run_id: str
    goal_hash: str
    phase: str = ""
    step: str = ""
    budgets: tuple[tuple[str, Any], ...] = ()
    leases: tuple[str, ...] = ()
    provider_state: tuple[tuple[str, Any], ...] = ()
    effects: tuple[RunEffect, ...] = ()
    receipts: tuple[str, ...] = ()
    state: RunState = RunState.PLANNED
    created_at_ns: int = 0
    updated_at_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        object.__setattr__(self, "goal_hash", _text(self.goal_hash, "goal_hash"))
        object.__setattr__(self, "phase", str(self.phase).strip())
        object.__setattr__(self, "step", str(self.step).strip())
        object.__setattr__(self, "budgets", _pairs(self.budgets, "budgets"))
        object.__setattr__(
            self,
            "provider_state",
            _pairs(self.provider_state, "provider_state", reject_sensitive=True),
        )
        object.__setattr__(self, "leases", _refs(self.leases, "leases"))
        object.__setattr__(self, "receipts", _refs(self.receipts, "receipts"))
        effects = tuple(
            item if isinstance(item, RunEffect) else RunEffect.from_dict(item)
            for item in self.effects
        )
        if len({item.effect_id for item in effects}) != len(effects):
            raise PersistentRunError(
                "effects must not contain duplicate effect_id values"
            )
        object.__setattr__(self, "effects", effects)
        if not isinstance(self.state, RunState):
            object.__setattr__(self, "state", RunState(self.state))
        if not isinstance(self.created_at_ns, int) or self.created_at_ns < 0:
            raise PersistentRunError("created_at_ns must be a non-negative integer")
        if (
            not isinstance(self.updated_at_ns, int)
            or self.updated_at_ns < self.created_at_ns
        ):
            raise PersistentRunError("updated_at_ns must be >= created_at_ns")
        if self.state is RunState.COMPLETED and not self.can_complete:
            raise CompletionNotReady(
                "completed runs require receipts and reconciled effects"
            )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        goal_hash: str,
        phase: str = "",
        step: str = "",
        budgets: Mapping[str, Any] = (),
        leases: tuple[str, ...] | list[str] = (),
        provider_state: Mapping[str, Any] = (),
        now_ns: int | None = None,
    ) -> "PersistentRun":
        timestamp = time.time_ns() if now_ns is None else now_ns
        return cls(
            run_id=run_id,
            goal_hash=goal_hash,
            phase=phase,
            step=step,
            budgets=budgets,
            leases=tuple(leases),
            provider_state=provider_state,
            created_at_ns=timestamp,
            updated_at_ns=timestamp,
        )

    @property
    def schema(self) -> str:
        return PERSISTENT_RUN_SCHEMA

    @property
    def schema_version(self) -> str:
        return PERSISTENT_RUN_SCHEMA_VERSION

    @property
    def can_complete(self) -> bool:
        return bool(self.receipts) and all(
            effect.status in {RunEffectStatus.COMMITTED, RunEffectStatus.RECONCILED}
            for effect in self.effects
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL

    def resume_contract(self) -> dict[str, Any]:
        """Return the safe boundary a restarted worker must revalidate."""

        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "goal_hash": self.goal_hash,
            "state": self.state.value,
            "phase": self.phase,
            "step": self.step,
            "revalidate_environment": self.state
            not in {RunState.CANCELLED, RunState.FAILED},
            "effect_statuses": {
                effect.idempotency_key: effect.status.value
                for effect in self.effects
            },
            "committed_effects": tuple(
                effect.idempotency_key
                for effect in self.effects
                if effect.status is RunEffectStatus.COMMITTED
            ),
        }

    def transition(
        self, state: RunState | str, *, now_ns: int | None = None
    ) -> "PersistentRun":
        target = state if isinstance(state, RunState) else RunState(state)
        if target is self.state:
            return self
        if target not in _ALLOWED.get(self.state, frozenset()):
            raise InvalidRunTransition(
                f"invalid run transition {self.state.value!r} -> {target.value!r}"
            )
        if target is RunState.COMPLETED and not self.can_complete:
            raise CompletionNotReady(
                "completed runs require receipts and reconciled effects"
            )
        timestamp = time.time_ns() if now_ns is None else now_ns
        if timestamp < self.updated_at_ns:
            raise PersistentRunError("updated_at_ns must not move backwards")
        return replace(self, state=target, updated_at_ns=timestamp)

    def record_effect(
        self, effect: RunEffect, *, now_ns: int | None = None
    ) -> "PersistentRun":
        if not isinstance(effect, RunEffect):
            raise TypeError("effect must be a RunEffect")
        for index, current in enumerate(self.effects):
            if current.effect_id != effect.effect_id:
                continue
            if current == effect:
                return self
            if current.status is RunEffectStatus.COMMITTED:
                raise DuplicateCommittedEffect(effect.effect_id)
            updated = list(self.effects)
            updated[index] = effect
            timestamp = time.time_ns() if now_ns is None else now_ns
            return replace(
                self,
                effects=tuple(updated),
                updated_at_ns=max(timestamp, self.updated_at_ns),
            )
        timestamp = time.time_ns() if now_ns is None else now_ns
        return replace(
            self,
            effects=self.effects + (effect,),
            updated_at_ns=max(timestamp, self.updated_at_ns),
        )

    def add_receipt(
        self, receipt: str, *, now_ns: int | None = None
    ) -> "PersistentRun":
        receipt = _text(receipt, "receipt")
        if receipt in self.receipts:
            return self
        timestamp = time.time_ns() if now_ns is None else now_ns
        return replace(
            self,
            receipts=self.receipts + (receipt,),
            updated_at_ns=max(timestamp, self.updated_at_ns),
        )

    def content_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "goal_hash": self.goal_hash,
            "phase": self.phase,
            "step": self.step,
            "budgets": dict(self.budgets),
            "leases": list(self.leases),
            "provider_state": dict(self.provider_state),
            "effects": [effect.to_dict() for effect in self.effects],
            "receipts": list(self.receipts),
            "state": self.state.value,
            "created_at_ns": self.created_at_ns,
            "updated_at_ns": self.updated_at_ns,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            indent=indent,
            separators=None if indent else (",", ":"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PersistentRun":
        if (
            data.get("schema") != PERSISTENT_RUN_SCHEMA
            or data.get("schema_version") != PERSISTENT_RUN_SCHEMA_VERSION
        ):
            raise PersistentRunError("unsupported persistent-run schema")
        return cls(
            run_id=data["run_id"],
            goal_hash=data["goal_hash"],
            phase=data.get("phase", ""),
            step=data.get("step", ""),
            budgets=tuple(
                (key, value) for key, value in data.get("budgets", {}).items()
            ),
            leases=tuple(data.get("leases", ())),
            provider_state=tuple(
                (key, value) for key, value in data.get("provider_state", {}).items()
            ),
            effects=tuple(
                RunEffect.from_dict(item) for item in data.get("effects", ())
            ),
            receipts=tuple(data.get("receipts", ())),
            state=data.get("state", RunState.PLANNED),
            created_at_ns=int(data.get("created_at_ns", 0)),
            updated_at_ns=int(data.get("updated_at_ns", 0)),
        )

    @classmethod
    def from_json(cls, text: str) -> "PersistentRun":
        return cls.from_dict(json.loads(text))


__all__ = [
    "PERSISTENT_RUN_SCHEMA",
    "PERSISTENT_RUN_SCHEMA_VERSION",
    "RunState",
    "RunEffectStatus",
    "RunEffect",
    "PersistentRun",
    "PersistentRunError",
    "InvalidRunTransition",
    "DuplicateCommittedEffect",
    "CompletionNotReady",
]
