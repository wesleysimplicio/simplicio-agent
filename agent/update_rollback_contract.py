"""Bounded update, flags, and rollback contract for issue #129.

This module is deliberately additive and side-effect free.  It validates the
evidence a future updater would need, produces a deterministic receipt, and
never downloads, installs, restarts, calls Google/Stripe, or performs a
rollback.  ``ready`` therefore means "the contract is complete", not that an
updater has run.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Any, Final, Mapping


ISSUE_NUMBER: Final = 129
CONTRACT_SCHEMA: Final = "simplicio-agent/update-rollback-contract/v1"
DEFAULT_FLAGS: Final = {"google_enabled": False, "stripe_enabled": False}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RANGE_MARKERS = ("*", "^", "~", ">", "<", "=")


class ReadinessStatus(StrEnum):
    """Whether the evidence contract is complete for a caller-owned updater."""

    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ModelVersionPin:
    """An exact model/version pair; ranges are intentionally not accepted."""

    model: str = ""
    version: str = ""

    @property
    def is_valid(self) -> bool:
        return _exact_text(self.model) and _exact_version(self.version)

    @property
    def key(self) -> str:
        return f"{self.model.strip()}@{self.version.strip()}"


@dataclass(frozen=True)
class IntegrationFlags:
    """Feature flags carried by an update; external integrations default off."""

    google_enabled: bool = False
    stripe_enabled: bool = False
    demo_mode: bool = False
    demo_mode_explicit: bool = False

    @property
    def default_off(self) -> bool:
        return self.google_enabled is False and self.stripe_enabled is False

    @property
    def is_valid(self) -> bool:
        return (
            isinstance(self.google_enabled, bool)
            and isinstance(self.stripe_enabled, bool)
            and isinstance(self.demo_mode, bool)
            and isinstance(self.demo_mode_explicit, bool)
            and (not self.demo_mode or self.demo_mode_explicit)
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "google_enabled": self.google_enabled,
            "stripe_enabled": self.stripe_enabled,
            "demo_mode": self.demo_mode,
            "demo_mode_explicit": self.demo_mode_explicit,
        }


@dataclass(frozen=True)
class UpdateApproval:
    """Explicit approval evidence required before an update can be staged."""

    approved: bool = False
    approved_by: str = ""
    approval_id: str = ""
    receipt: str = ""
    scope: str = "update"

    @property
    def is_valid(self) -> bool:
        return (
            self.approved is True
            and _exact_text(self.approved_by)
            and _exact_text(self.approval_id)
            and _exact_text(self.receipt)
            and _exact_text(self.scope)
        )


@dataclass(frozen=True)
class ChecksumEvidence:
    """A SHA-256 checksum tied to an artifact and a verification receipt."""

    artifact: str = ""
    sha256: str = ""
    receipt: str = ""

    @property
    def is_valid(self) -> bool:
        return (
            _exact_text(self.artifact)
            and isinstance(self.sha256, str)
            and _SHA256_RE.fullmatch(self.sha256.strip()) is not None
            and _exact_text(self.receipt)
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact": self.artifact.strip(),
            "sha256": self.sha256.strip().lower(),
            "receipt": self.receipt.strip(),
        }


@dataclass(frozen=True)
class RollbackTarget:
    """The exact artifact to restore and proof that rollback was verified."""

    model_version_pin: ModelVersionPin | None = None
    artifact: str = ""
    checksum: ChecksumEvidence | None = None
    proof_receipt: str = ""
    proof_verified: bool = False

    @property
    def proof_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.model_version_pin is None or not self.model_version_pin.is_valid:
            errors.append("target model version pin is missing or invalid")
        if not _exact_text(self.artifact):
            errors.append("target artifact is missing")
        if self.checksum is None or not self.checksum.is_valid:
            errors.append("target checksum evidence is missing or invalid")
        elif self.checksum.artifact.strip() != self.artifact.strip():
            errors.append("target checksum is not tied to the target artifact")
        if self.proof_verified is not True:
            errors.append("rollback verification is not marked complete")
        if not _exact_text(self.proof_receipt):
            errors.append("rollback proof receipt is missing")
        return tuple(errors)

    @property
    def is_proven(self) -> bool:
        return not self.proof_errors


@dataclass(frozen=True)
class UpdateRollbackContract:
    """Pure input contract for a staged update with a proven rollback target."""

    model_version_pin: ModelVersionPin | None = None
    update_artifact: str = ""
    update_checksum: ChecksumEvidence | None = None
    approval: UpdateApproval = UpdateApproval()
    rollback_target: RollbackTarget | None = None
    flags: IntegrationFlags = IntegrationFlags()
    operation_id: str = ""
    issue_number: int = ISSUE_NUMBER

    @property
    def integrations(self) -> IntegrationFlags:
        """Compatibility name for callers that describe flags as integrations."""

        return self.flags

    def validation_errors(self) -> tuple[str, ...]:
        """Return deterministic blockers; callers must treat any blocker as fatal."""

        blockers: list[str] = []
        if self.model_version_pin is None:
            blockers.append("model version pin: missing")
        elif not self.model_version_pin.is_valid:
            blockers.append("model version pin: invalid exact pin")

        if not _exact_text(self.update_artifact):
            blockers.append("update artifact: missing")
        if self.update_checksum is None:
            blockers.append("update checksum: missing")
        elif not self.update_checksum.is_valid:
            blockers.append("update checksum: invalid SHA-256 evidence")
        elif self.update_checksum.artifact.strip() != self.update_artifact.strip():
            blockers.append("update checksum: not tied to update artifact")

        if not self.approval.is_valid:
            blockers.append("update approval: missing or invalid")

        if not self.flags.is_valid:
            blockers.append("flags: demo mode requires an explicit flag")
        if not self.flags.default_off:
            blockers.append("flags: Google and Stripe must remain default-off")

        if self.rollback_target is None:
            blockers.append("rollback proof: missing rollback target and proof")
        elif not self.rollback_target.is_proven:
            blockers.append(
                "rollback proof: "
                + "; ".join(self.rollback_target.proof_errors)
            )
        return tuple(blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "model_version_pin": _to_json_value(self.model_version_pin),
            "update_artifact": self.update_artifact.strip(),
            "update_checksum": _to_json_value(self.update_checksum),
            "approval": _to_json_value(self.approval),
            "rollback_target": _to_json_value(self.rollback_target),
            "flags": self.flags.to_dict(),
            "operation_id": self.operation_id.strip(),
            "issue_number": self.issue_number,
        }


@dataclass(frozen=True)
class UpdateReceipt:
    """Content-addressed result receipt; equivalent requests get one identity."""

    schema: str
    status: ReadinessStatus
    request_sha256: str
    receipt_sha256: str
    blockers: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        contract: UpdateRollbackContract,
        status: ReadinessStatus,
        blockers: tuple[str, ...],
    ) -> "UpdateReceipt":
        payload = {
            "contract": contract.to_dict(),
            "status": status.value,
            "blockers": list(blockers),
        }
        canonical = _canonical_json(payload)
        request_sha = hashlib.sha256(
            _canonical_json(contract.to_dict()).encode("utf-8")
        ).hexdigest()
        receipt_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return cls(
            schema=CONTRACT_SCHEMA,
            status=status,
            request_sha256=request_sha,
            receipt_sha256=receipt_sha,
            blockers=tuple(blockers),
        )

    @property
    def idempotency_key(self) -> str:
        return f"{self.schema}:{self.receipt_sha256}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status.value,
            "request_sha256": self.request_sha256,
            "receipt_sha256": self.receipt_sha256,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class UpdateRollbackAudit:
    """Evidence-gated audit result, never an updater execution result."""

    readiness: ReadinessStatus
    blockers: tuple[str, ...]
    verified_checks: tuple[str, ...]
    receipt: UpdateReceipt

    @property
    def is_ready(self) -> bool:
        return self.readiness is ReadinessStatus.READY

    @property
    def contract_ready(self) -> bool:
        return self.is_ready

    def to_dict(self) -> dict[str, object]:
        return {
            "readiness": self.readiness.value,
            "blockers": list(self.blockers),
            "verified_checks": list(self.verified_checks),
            "receipt": self.receipt.to_dict(),
        }


def audit_update_rollback(
    contract: UpdateRollbackContract | None = None,
    **kwargs: Any,
) -> UpdateRollbackAudit:
    """Evaluate evidence without invoking or claiming an updater integration."""

    if contract is not None and kwargs:
        raise ValueError("provide either contract or keyword fields, not both")
    item = contract or UpdateRollbackContract(**kwargs)
    blockers = item.validation_errors()
    verified = () if blockers else (
        "model-version-pin",
        "update-checksum",
        "update-approval",
        "default-off-integrations",
        "rollback-proof",
    )
    readiness = ReadinessStatus.READY if not blockers else ReadinessStatus.BLOCKED
    receipt = UpdateReceipt.create(
        contract=item,
        status=readiness,
        blockers=blockers,
    )
    return UpdateRollbackAudit(
        readiness=readiness,
        blockers=blockers,
        verified_checks=verified,
        receipt=receipt,
    )


def _exact_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value


def _exact_version(value: object) -> bool:
    return (
        _exact_text(value)
        and not any(marker in str(value).strip() for marker in _RANGE_MARKERS)
        and " " not in str(value).strip()
    )


def _to_json_value(value: Any) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _to_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_json_value(item) for item in value]
    return str(value)


def _canonical_json(value: object) -> str:
    return json.dumps(
        _to_json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "CONTRACT_SCHEMA",
    "DEFAULT_FLAGS",
    "ISSUE_NUMBER",
    "ChecksumEvidence",
    "IntegrationFlags",
    "ModelVersionPin",
    "ReadinessStatus",
    "RollbackTarget",
    "UpdateApproval",
    "UpdateReceipt",
    "UpdateRollbackAudit",
    "UpdateRollbackContract",
    "audit_update_rollback",
]
