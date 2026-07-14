"""Bounded atomic promotion controller for the native update boundary.

The controller owns only the promotion edge: a content-addressed slot is
prepared and verified, ``current`` is swapped atomically, and a live process
attestation is checked before the promotion is committed.  It deliberately
does not start or stop processes; a failed attestation returns a durable
rollback intent for the supervisor and restores the previous pointer.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from tools.transaction_primitives import TransactionJournal, snapshot_tree


PROMOTION_SCHEMA = "simplicio.promotion/v1"
POINTER_SCHEMA = "simplicio.promotion-pointer/v1"
_DIGEST_LENGTH = 64
_ACTIVE_LEASE_STATES = frozenset({"claimed", "active", "renewed"})


class PromotionError(RuntimeError):
    """A promotion cannot safely proceed."""


class PromotionReceiptError(PromotionError):
    """The promotion report is absent, malformed, or stale."""


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _nested(value: Mapping[str, Any], *keys: str) -> object | None:
    current: object = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first(value: Mapping[str, Any], *paths: tuple[str, ...]) -> object | None:
    for path in paths:
        candidate = _nested(value, *path)
        if candidate is not None:
            return candidate
    return None


def _receipt_fields(
    receipt: Mapping[str, Any],
) -> tuple[object, object, object, object]:
    """Read the canonical shape and the report shape emitted by Native 1.3."""

    before = _first(
        receipt,
        ("snapshot_before",),
        ("before_snapshot",),
        ("before", "snapshot"),
        ("before", "snapshot_id"),
        ("promote", "snapshot_before"),
    )
    candidate = _first(
        receipt,
        ("candidate_digest",),
        ("promoted_digest",),
        ("after_digest",),
        ("after", "digest"),
        ("promote", "candidate_digest"),
    )
    commit = _first(
        receipt,
        ("promoted_commit",),
        ("after_commit",),
        ("commit",),
        ("after", "commit"),
        ("promote", "commit"),
    )
    lease = receipt.get("lease")
    token = _first(receipt, ("fencing_token",), ("promote", "fencing_token"))
    if isinstance(lease, Mapping):
        token = token if token is not None else lease.get("fencing_token")
    return before, candidate, commit, token


def validate_promotion_receipt(
    receipt: Mapping[str, Any], *, now: float | None = None
) -> list[str]:
    """Return deterministic validation errors for a Native 1.4 receipt."""

    errors: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["promotion receipt must be an object"]
    if receipt.get("schema") != PROMOTION_SCHEMA:
        errors.append(f"schema must be {PROMOTION_SCHEMA}")
    if receipt.get("operation", receipt.get("intent")) != "promote":
        errors.append("operation must be promote")
    before, candidate, commit, token = _receipt_fields(receipt)
    if not _digest(before):
        errors.append("snapshot_before must be a 64-character lowercase digest")
    if not _digest(candidate):
        errors.append("candidate_digest must be a 64-character lowercase digest")
    if not _text(commit):
        errors.append("promoted_commit must be a non-empty string")
    try:
        if int(token) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("lease.fencing_token must be a positive integer")

    lease = receipt.get("lease")
    if not isinstance(lease, Mapping):
        errors.append("lease must be an object")
    else:
        if lease.get("status") not in _ACTIVE_LEASE_STATES:
            errors.append("lease.status must be active")
        expires_at = lease.get("expires_at")
        if expires_at is not None:
            try:
                if now is not None and float(expires_at) < now:
                    errors.append("lease has expired")
            except (TypeError, ValueError):
                errors.append("lease.expires_at must be numeric")
    return sorted(set(errors))


def build_promotion_receipt(
    *,
    snapshot_before: str,
    candidate_digest: str,
    promoted_commit: str,
    fencing_token: int,
    lease_status: str = "claimed",
    lease_expires_at: float | None = None,
) -> dict[str, Any]:
    """Build the canonical report consumed by :class:`PromotionController`."""

    lease: dict[str, Any] = {
        "status": lease_status,
        "fencing_token": fencing_token,
    }
    if lease_expires_at is not None:
        lease["expires_at"] = lease_expires_at
    return {
        "schema": PROMOTION_SCHEMA,
        "operation": "promote",
        "snapshot_before": snapshot_before,
        "candidate_digest": candidate_digest,
        "promoted_commit": promoted_commit,
        "lease": lease,
    }


@dataclass(frozen=True)
class HealthCheckReport:
    """The minimum live-process attestation required for a commit."""

    healthy: bool
    commit: str | None = None
    digest: str | None = None
    smoke: bool | None = None
    subsystems: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def from_value(cls, value: object) -> "HealthCheckReport":
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            return cls(value)
        if not isinstance(value, Mapping):
            return cls(False, reason="health_check_invalid_response")
        healthy = value.get(
            "healthy", value.get("ok", value.get("status") == "healthy")
        )
        digest = value.get("digest", value.get("commit_digest"))
        smoke = value.get("smoke")
        return cls(
            bool(healthy),
            _text(value.get("commit")),
            _text(digest),
            bool(smoke) if smoke is not None else None,
            value.get("subsystems", {}),
            _text(value.get("reason")),
        )

    def failure_reason(self, expected_commit: str, expected_digest: str) -> str | None:
        if not self.healthy:
            return self.reason or "health_check_failed"
        if self.commit != expected_commit:
            return "live_commit_mismatch"
        if self.digest != expected_digest:
            return "live_digest_mismatch"
        if self.smoke is False:
            return "health_smoke_failed"
        return None


@dataclass(frozen=True)
class RollbackIntent:
    """Supervisor intent emitted after an activated candidate fails live checks."""

    reason: str
    from_digest: str
    to_digest: str
    action: str = "restore_snapshot_and_restart"
    status: str = "requested"
    automatic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "automatic_rollback",
            "reason": self.reason,
            "from_digest": self.from_digest,
            "to_digest": self.to_digest,
            "action": self.action,
            "status": self.status,
            "automatic": self.automatic,
        }


@dataclass(frozen=True)
class PromotionResult:
    promoted: bool
    rolled_back: bool
    before_digest: str
    after_digest: str
    health: HealthCheckReport
    rollback_intent: RollbackIntent | None = None

    @property
    def rollback_requested(self) -> bool:
        return self.rollback_intent is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROMOTION_SCHEMA,
            "promoted": self.promoted,
            "rolled_back": self.rolled_back,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "health": {
                "healthy": self.health.healthy,
                "commit": self.health.commit,
                "digest": self.health.digest,
                "smoke": self.health.smoke,
                "reason": self.health.reason,
            },
            "rollback_intent": (
                self.rollback_intent.to_dict() if self.rollback_intent else None
            ),
        }


@dataclass(frozen=True)
class HealthCheckContext:
    slot: Path
    digest: str
    commit: str


class PromotionController:
    """Prepare slots and atomically promote one after live attestation."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.slots = self.root / "slots"
        self.pointer = self.root / "current"
        self.journal = TransactionJournal(self.root / "promotion-journal.jsonl")

    def current(self) -> str | None:
        """Return the digest addressed by ``current`` or ``None`` initially."""

        if not self.pointer.exists() and not self.pointer.is_symlink():
            return None
        try:
            target = (
                os.readlink(self.pointer)
                if self.pointer.is_symlink()
                else self.pointer.read_text(encoding="utf-8").strip()
            )
            if target.startswith("{"):
                value = json.loads(target)
                target = str(value["target"])
            target = target.replace("\\", "/")
            prefix = "slots/"
            if target.startswith("./"):
                target = target[2:]
            if not target.startswith(prefix):
                raise ValueError
            digest = target[len(prefix) :].rstrip("/")
            if not _digest(digest) or not (self.slots / digest).is_dir():
                raise ValueError
            return digest
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PromotionError("current pointer is invalid") from exc

    def seed(self, source: Path) -> str:
        """Install an initial verified slot for tests/bootstrap, without promotion."""

        digest = self.stage(source)
        self._swap_pointer(digest)
        self.journal.append("seed", {"after": digest})
        return digest

    def stage(self, source: Path) -> str:
        """Copy and verify a source tree into an immutable content-addressed slot."""

        source = Path(source).expanduser().resolve()
        if source.is_symlink() or not source.is_dir():
            raise PromotionError("promotion source must be a real directory")
        self.slots.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".slot-", dir=self.slots))
        try:
            shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=False)
            digest = snapshot_tree(temporary).snapshot_id
            destination = self.slots / digest
            if destination.exists():
                if (
                    not destination.is_dir()
                    or snapshot_tree(destination).snapshot_id != digest
                ):
                    raise PromotionError("existing promotion slot has the wrong digest")
                shutil.rmtree(temporary)
            else:
                os.replace(temporary, destination)
            return digest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def promote(
        self,
        source: Path,
        receipt: Mapping[str, Any],
        health_check: Callable[..., object],
        *,
        timeout_s: float = 60.0,
        now: float | None = None,
    ) -> PromotionResult:
        """Promote ``source`` iff the receipt and live attestation both pass."""

        errors = validate_promotion_receipt(
            receipt, now=time.time() if now is None else now
        )
        if errors:
            raise PromotionReceiptError(
                "invalid promotion receipt: " + "; ".join(errors)
            )
        before, expected_digest, expected_commit, _token = _receipt_fields(receipt)
        assert isinstance(before, str)
        assert isinstance(expected_digest, str)
        assert isinstance(expected_commit, str)
        current = self.current()
        if current != before:
            raise PromotionReceiptError(
                "promotion receipt snapshot_before is not current"
            )
        candidate = self.stage(source)
        if candidate != expected_digest:
            raise PromotionReceiptError(
                "staged slot digest does not match promotion receipt"
            )
        self._swap_pointer(candidate)
        self.journal.append(
            "activate",
            {"before": before, "after": candidate, "commit": expected_commit},
        )
        health = self._run_health_check(
            health_check,
            HealthCheckContext(self.slots / candidate, candidate, expected_commit),
            timeout_s,
        )
        reason = health.failure_reason(expected_commit, candidate)
        if reason is not None:
            intent = RollbackIntent(reason, candidate, before)
            self._swap_pointer(before)
            self.journal.append(
                "rollback_intent",
                {"before": candidate, "after": before, **intent.to_dict()},
            )
            return PromotionResult(False, True, before, candidate, health, intent)
        self.journal.append(
            "commit", {"snapshot": candidate, "commit": expected_commit}
        )
        return PromotionResult(True, False, before, candidate, health)

    def _run_health_check(
        self,
        callback: Callable[..., object],
        context: HealthCheckContext,
        timeout_s: float,
    ) -> HealthCheckReport:
        if timeout_s <= 0:
            return HealthCheckReport(False, reason="health_check_timeout")
        result: list[object] = []
        finished = threading.Event()

        def run() -> None:
            try:
                parameters = inspect.signature(callback).parameters
                value = callback(context.slot) if parameters else callback()
                result.append(value)
            except Exception as exc:  # health probes fail closed
                result.append(
                    HealthCheckReport(
                        False, reason=f"health_check_error:{type(exc).__name__}"
                    )
                )
            finally:
                finished.set()

        threading.Thread(
            target=run, name="simplicio-promotion-health", daemon=True
        ).start()
        if not finished.wait(timeout_s):
            return HealthCheckReport(False, reason="health_check_timeout")
        return HealthCheckReport.from_value(result[0] if result else None)

    def _swap_pointer(self, digest: str) -> None:
        if not _digest(digest) or not (self.slots / digest).is_dir():
            raise PromotionError("cannot point current at an unavailable slot")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".current-{os.getpid()}-{threading.get_ident()}"
        temporary.unlink(missing_ok=True)
        target = f"slots/{digest}"
        try:
            try:
                os.symlink(target, temporary, target_is_directory=True)
            except (OSError, NotImplementedError):
                temporary.write_text(target + "\n", encoding="utf-8")
            os.replace(temporary, self.pointer)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "HealthCheckContext",
    "HealthCheckReport",
    "POINTER_SCHEMA",
    "PROMOTION_SCHEMA",
    "PromotionController",
    "PromotionError",
    "PromotionReceiptError",
    "PromotionResult",
    "RollbackIntent",
    "build_promotion_receipt",
    "validate_promotion_receipt",
]
