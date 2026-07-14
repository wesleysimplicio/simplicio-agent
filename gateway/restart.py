"""Shared gateway restart constants and bounded effect recovery helpers.

The gateway can lose a response after an external side effect has been
accepted (for example, while the process is shutting down).  This module
keeps the restart boundary deliberately small: a durable observation is
replayed after restart, while an absent or ambiguous observation is never
treated as permission to execute again.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from hermes_cli.config import DEFAULT_CONFIG

# EX_TEMPFAIL from sysexits.h — used to ask the service manager to restart
# the gateway after a graceful drain/reload path completes.
GATEWAY_SERVICE_RESTART_EXIT_CODE = 75

# EX_CONFIG from sysexits.h — fatal configuration error (e.g. token
# collision, no messaging platforms).  The s6 finish script translates
# this into exit 125 (permanent failure) so the supervisor stops
# restarting the gateway.  See #51228.
GATEWAY_FATAL_CONFIG_EXIT_CODE = 78

DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT = float(
    DEFAULT_CONFIG["agent"]["restart_drain_timeout"]
)


def parse_restart_drain_timeout(raw: object) -> float:
    """Parse a configured drain timeout, falling back to the shared default."""
    try:
        value = (
            float(raw)
            if str(raw or "").strip()
            else DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT
        )
    except (TypeError, ValueError):
        return DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT
    return max(0.0, value)


RESTART_EFFECT_SCHEMA = "simplicio.gateway-restart-effect"
RESTART_EFFECT_SCHEMA_VERSION = "simplicio.gateway-restart-effect/v1"


class EffectState(str, Enum):
    """Durable observations for an idempotency-sensitive gateway effect."""

    PENDING = "pending"
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    UNKNOWN = "unknown"


class RecoveryDecision(str, Enum):
    """The only restart decisions exposed to a caller."""

    SKIP_COMMITTED = "skip_committed"
    RETRY = "retry"
    RECONCILE_UNKNOWN = "reconcile_unknown"


class RestartJournalCorruptError(ValueError):
    """Raised when a durable restart-effect journal cannot be reconstructed."""


class RestartEffectConflictError(ValueError):
    """Raised when an effect identity attempts an unsafe state transition."""


@dataclass(frozen=True)
class RestartEffectRecord:
    """One fsynced effect observation.

    ``task_id`` and ``correlation_id`` are intentionally carried beside the
    idempotency key.  A matching key from a different causal chain is
    ambiguous and must be reconciled, never replayed.
    """

    effect_id: str
    idempotency_key: str
    task_id: str
    correlation_id: str
    state: EffectState
    receipt: Optional[str] = None
    reason: Optional[str] = None
    recorded_at_ns: int = 0
    schema: str = RESTART_EFFECT_SCHEMA
    schema_version: str = RESTART_EFFECT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema != RESTART_EFFECT_SCHEMA:
            raise RestartJournalCorruptError(f"unsupported schema: {self.schema!r}")
        if self.schema_version != RESTART_EFFECT_SCHEMA_VERSION:
            raise RestartJournalCorruptError(
                f"unsupported schema version: {self.schema_version!r}"
            )
        if not self.effect_id or not self.idempotency_key:
            raise RestartJournalCorruptError(
                "effect_id and idempotency_key are required"
            )
        if self.recorded_at_ns < 0:
            raise RestartJournalCorruptError("recorded_at_ns must be non-negative")

    @classmethod
    def pending(
        cls,
        *,
        effect_id: str,
        idempotency_key: str,
        task_id: str = "",
        correlation_id: str = "",
        now_ns: Optional[int] = None,
    ) -> "RestartEffectRecord":
        return cls(
            effect_id=effect_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            correlation_id=correlation_id,
            state=EffectState.PENDING,
            recorded_at_ns=time.time_ns() if now_ns is None else now_ns,
        )

    def resolve(
        self,
        state: EffectState,
        *,
        receipt: Optional[str] = None,
        reason: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> "RestartEffectRecord":
        if state is EffectState.PENDING:
            raise RestartEffectConflictError("an effect cannot resolve to pending")
        return RestartEffectRecord(
            effect_id=self.effect_id,
            idempotency_key=self.idempotency_key,
            task_id=self.task_id,
            correlation_id=self.correlation_id,
            state=state,
            receipt=receipt if receipt is not None else self.receipt,
            reason=reason if reason is not None else self.reason,
            recorded_at_ns=time.time_ns() if now_ns is None else now_ns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "idempotency_key": self.idempotency_key,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "state": self.state.value,
            "receipt": self.receipt,
            "reason": self.reason,
            "recorded_at_ns": self.recorded_at_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RestartEffectRecord":
        try:
            return cls(
                schema=data["schema"],
                schema_version=data["schema_version"],
                effect_id=str(data["effect_id"]),
                idempotency_key=str(data["idempotency_key"]),
                task_id=str(data.get("task_id", "")),
                correlation_id=str(data.get("correlation_id", "")),
                state=EffectState(data["state"]),
                receipt=data.get("receipt"),
                reason=data.get("reason"),
                recorded_at_ns=int(data["recorded_at_ns"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RestartJournalCorruptError):
                raise
            raise RestartJournalCorruptError(f"invalid effect record: {exc}") from exc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RestartEffectRecord":
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise RestartJournalCorruptError(f"invalid effect JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RestartJournalCorruptError("effect JSON must be an object")
        return cls.from_dict(value)


@dataclass(frozen=True)
class RecoveryResult:
    """A restart decision; ``should_execute`` is the sole retry gate."""

    decision: RecoveryDecision
    observed_state: EffectState
    reason: str
    record: Optional[RestartEffectRecord]

    @property
    def should_execute(self) -> bool:
        return self.decision is RecoveryDecision.RETRY


class RestartEffectJournal:
    """Durable JSONL journal with idempotent appends and monotonic commits.

    The caller-owned idempotency key is the durable identity.  ``effect_id``
    remains part of the causal receipt, but cannot be changed to make a replay
    look like a new effect after restart.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: dict[str, RestartEffectRecord] = {}
        self._load()

    @staticmethod
    def _key(record: RestartEffectRecord) -> str:
        return record.idempotency_key

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RestartJournalCorruptError(f"cannot read journal: {exc}") from exc
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                self._accept(RestartEffectRecord.from_json(line), persist=False)
            except (RestartJournalCorruptError, RestartEffectConflictError) as exc:
                raise RestartJournalCorruptError(
                    f"journal line {line_no}: {exc}"
                ) from exc

    def _accept(
        self, record: RestartEffectRecord, *, persist: bool
    ) -> RestartEffectRecord:
        key = self._key(record)
        previous = self._records.get(key)
        if previous == record:
            return previous
        if previous is not None:
            if (
                previous.effect_id != record.effect_id
                or previous.task_id != record.task_id
                or previous.correlation_id != record.correlation_id
            ):
                raise RestartEffectConflictError(
                    "idempotency key belongs to another causal chain"
                )
            if previous.state is EffectState.COMMITTED:
                raise RestartEffectConflictError(
                    "committed effect cannot be superseded"
                )
            if record.state is EffectState.PENDING:
                raise RestartEffectConflictError(
                    f"pending observation cannot follow {previous.state.value}"
                )
        self._records[key] = record
        if persist:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(record.to_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                if previous is None:
                    self._records.pop(key, None)
                else:
                    self._records[key] = previous
                raise OSError(f"cannot persist restart effect: {exc}") from exc
        return record

    def append(self, record: RestartEffectRecord) -> RestartEffectRecord:
        """Append an observation; an exact duplicate is a no-op."""

        return self._accept(record, persist=True)

    def _latest_for_key(
        self, idempotency_key: str
    ) -> Optional[RestartEffectRecord]:
        return self._records.get(idempotency_key)

    def latest(
        self, *, effect_id: str, idempotency_key: str
    ) -> Optional[RestartEffectRecord]:
        record = self._latest_for_key(idempotency_key)
        return record if record is not None and record.effect_id == effect_id else None

    def begin(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        task_id: str = "",
        correlation_id: str = "",
        now_ns: Optional[int] = None,
    ) -> RestartEffectRecord:
        existing = self._latest_for_key(idempotency_key)
        if existing is not None:
            if (
                existing.effect_id != effect_id
                or existing.task_id != task_id
                or existing.correlation_id != correlation_id
            ):
                raise RestartEffectConflictError(
                    "idempotency key was reused with another causal chain"
                )
            return existing
        return self.append(
            RestartEffectRecord.pending(
                effect_id=effect_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                correlation_id=correlation_id,
                now_ns=now_ns,
            )
        )

    def resolve(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        state: EffectState,
        receipt: Optional[str] = None,
        reason: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> RestartEffectRecord:
        current = self._latest_for_key(idempotency_key)
        if current is None:
            raise KeyError(f"no pending effect {effect_id!r} for idempotency key")
        if current.effect_id != effect_id:
            raise RestartEffectConflictError(
                "idempotency key belongs to a different effect"
            )
        candidate = current.resolve(
            state, receipt=receipt, reason=reason, now_ns=now_ns
        )
        if current.state is EffectState.COMMITTED:
            if (
                candidate.state is EffectState.COMMITTED
                and candidate.receipt == current.receipt
                and candidate.reason == current.reason
            ):
                return current
            raise RestartEffectConflictError("committed effect cannot be downgraded")
        if current.state is candidate.state:
            if (
                candidate.receipt != current.receipt
                or candidate.reason != current.reason
            ):
                raise RestartEffectConflictError(
                    "conflicting duplicate effect observation"
                )
            return current
        return self.append(candidate)

    def recover(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> RecoveryResult:
        record = self._latest_for_key(idempotency_key)
        if record is None:
            return RecoveryResult(
                RecoveryDecision.RECONCILE_UNKNOWN,
                EffectState.UNKNOWN,
                "no durable effect record exists; commitment is unknown",
                None,
            )
        if (
            effect_id != record.effect_id
            or (task_id is not None and task_id != record.task_id)
            or (
                correlation_id is not None
                and correlation_id != record.correlation_id
            )
        ):
            return RecoveryResult(
                RecoveryDecision.RECONCILE_UNKNOWN,
                EffectState.UNKNOWN,
                "idempotency key belongs to a different effect, task, or correlation",
                record,
            )
        if record.state is EffectState.COMMITTED:
            return RecoveryResult(
                RecoveryDecision.SKIP_COMMITTED,
                record.state,
                "durable committed receipt exists; do not retry the effect",
                record,
            )
        if record.state is EffectState.NOT_COMMITTED:
            return RecoveryResult(
                RecoveryDecision.RETRY,
                record.state,
                record.reason or "verifier confirmed the effect was not committed",
                record,
            )
        return RecoveryResult(
            RecoveryDecision.RECONCILE_UNKNOWN,
            record.state,
            record.reason or "effect has no definitive commit outcome",
            record,
        )


# Short aliases keep the gateway surface consistent with the agent-level
# recovery contract without forcing gateway callers to import agent internals.
EffectRecord = RestartEffectRecord
EffectJournal = RestartEffectJournal
EffectJournalCorruptError = RestartJournalCorruptError
EffectStateConflictError = RestartEffectConflictError


def is_stale_restart_redelivery(
    event: Any,
    marker_path: str | Path,
    *,
    now: Optional[float] = None,
    max_age_seconds: float = 300.0,
) -> bool:
    """Return whether *event* matches a recent Telegram restart marker.

    This pure helper mirrors the existing marker contract and is safe to call
    from tests or future handlers without importing the gateway runner.  A
    missing, malformed, cross-platform, stale, or update-less marker is not a
    duplicate; callers can then process the command normally.
    """

    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    update_id = getattr(event, "platform_update_id", None)
    if (
        platform != "telegram"
        or isinstance(update_id, bool)
        or not isinstance(update_id, int)
    ):
        return False
    try:
        data = json.loads(Path(marker_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    if data.get("platform") != platform or not isinstance(data.get("update_id"), int):
        return False
    requested_at = data.get("requested_at")
    if not isinstance(requested_at, (int, float)) or isinstance(requested_at, bool):
        return False
    age = (time.time() if now is None else now) - requested_at
    if age < 0 or age > max(0.0, float(max_age_seconds)):
        return False
    return update_id <= data["update_id"]


__all__ = [
    "GATEWAY_SERVICE_RESTART_EXIT_CODE",
    "GATEWAY_FATAL_CONFIG_EXIT_CODE",
    "DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT",
    "parse_restart_drain_timeout",
    "RESTART_EFFECT_SCHEMA",
    "RESTART_EFFECT_SCHEMA_VERSION",
    "EffectState",
    "RecoveryDecision",
    "RestartJournalCorruptError",
    "RestartEffectConflictError",
    "RestartEffectRecord",
    "RecoveryResult",
    "RestartEffectJournal",
    "EffectRecord",
    "EffectJournal",
    "EffectJournalCorruptError",
    "EffectStateConflictError",
    "is_stale_restart_redelivery",
]
