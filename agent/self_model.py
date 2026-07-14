"""Bounded operational self-model receipts (issue #168).

The self-model is a deliberately small, immutable value layer.  It records
what the existing registry/health/policy sources say an agent can do; it does
not discover capabilities, grant authority, or alter the model tool schema.
Callers must provide a measured or canonical source receipt for each state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping


SELF_MODEL_SCHEMA = "simplicio.self-model/v1"
_SECRET_NAME = re.compile(
    r"(?:secret|password|passwd|credential)(?:$|[_-])"
    r"|api[_-]?key(?:$|[_-])|token(?:$|[_-])",
    re.I,
)
_TRUSTED_SOURCES = {"CANON", "MEASURED"}


class EvidenceClass(str, Enum):
    """Trust class accepted for a capability receipt."""

    MEASURED = "MEASURED"
    CANON = "CANON"


class CapabilityStatus(str, Enum):
    """The five independent dimensions of capability availability."""

    INSTALLED = "installed"
    CONFIGURED = "configured"
    HEALTHY = "healthy"
    AUTHORIZED = "authorized"
    VERIFIED = "verified"


class CapabilityTransition(str, Enum):
    """Observable transitions emitted when an actuator loses or regains health."""

    LOSS = "capability_loss"
    RECOVERY = "capability_recovery"


def _clean(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    if _SECRET_NAME.search(value):
        raise ValueError(f"{field_name} must not contain secret-like material")
    return value


def _safe_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        key = _clean(str(key), f"{field_name} key")
        if isinstance(item, Mapping):
            result[key] = _safe_mapping(item, f"{field_name}.{key}")
        elif isinstance(item, (list, tuple)):
            result[key] = [str(entry) for entry in item]
        else:
            result[key] = item
    return {key: result[key] for key in sorted(result)}


def _sorted_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    return tuple(sorted({_clean(value, field_name) for value in values}))


@dataclass(frozen=True)
class SourceReceipt:
    """Receipt proving the source of one self-model claim."""

    receipt_id: str
    evidence: EvidenceClass | str
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _clean(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "source", _clean(self.source, "source"))
        evidence = EvidenceClass(self.evidence)
        if evidence.value not in _TRUSTED_SOURCES:
            raise ValueError("self-model requires measured or canonical evidence")
        if self.source.casefold() in {"tool_output", "page", "browser_page"}:
            raise ValueError("untrusted tool/page output cannot attest self-model state")
        object.__setattr__(self, "evidence", evidence)

    def to_dict(self) -> dict[str, str]:
        return {
            "receipt_id": self.receipt_id,
            "evidence": self.evidence.value,
            "source": self.source,
        }


@dataclass(frozen=True)
class CapabilityState:
    """One capability's availability, authority, budget, and ownership bounds."""

    capability_id: str
    modality: str
    installed: bool
    configured: bool
    healthy: bool
    authorized: bool
    verified: bool
    authority_level: int
    authority_ceiling: int
    budget_remaining: int
    verifier_ref: str = ""
    rollback_ref: str = ""
    owner_scope: str = ""
    source_receipts: tuple[SourceReceipt, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _clean(self.capability_id, "capability_id"))
        object.__setattr__(self, "modality", _clean(self.modality, "modality"))
        if self.authority_level < 0 or self.authority_ceiling < 0:
            raise ValueError("authority levels must be non-negative")
        if self.authority_level > self.authority_ceiling:
            raise ValueError("authority cannot exceed its policy ceiling")
        if self.budget_remaining < 0:
            raise ValueError("budget_remaining must be non-negative")
        if self.verified and (not self.verifier_ref or not self.rollback_ref):
            raise ValueError("verified capability requires verifier and rollback refs")
        if self.authorized and not self.owner_scope:
            raise ValueError("authorized capability requires an owner scope")
        if self.verifier_ref:
            object.__setattr__(self, "verifier_ref", _clean(self.verifier_ref, "verifier_ref"))
        if self.rollback_ref:
            object.__setattr__(self, "rollback_ref", _clean(self.rollback_ref, "rollback_ref"))
        if self.owner_scope:
            object.__setattr__(self, "owner_scope", _clean(self.owner_scope, "owner_scope"))
        receipts = tuple(self.source_receipts)
        if not receipts:
            raise ValueError("capability state requires at least one source receipt")
        object.__setattr__(self, "source_receipts", receipts)
        object.__setattr__(self, "limitations", _sorted_strings(self.limitations, "limitation"))

    @property
    def available(self) -> bool:
        """Return whether every required availability dimension is true."""

        return all((self.installed, self.configured, self.healthy, self.authorized, self.verified))

    def with_health(self, healthy: bool, receipt: SourceReceipt, reason: str) -> "CapabilityState":
        """Return a loss/recovery update without changing authority or ownership."""

        if not isinstance(receipt, SourceReceipt):
            raise TypeError("health updates require a SourceReceipt")
        reason = _clean(reason, "health transition reason")
        limitations = set(self.limitations)
        if healthy:
            limitations.discard(reason)
        else:
            limitations.add(reason)
        return replace(
            self,
            healthy=healthy,
            source_receipts=self.source_receipts + (receipt,),
            limitations=tuple(limitations),
        )

    def attenuate(self, authority_level: int, receipt: SourceReceipt) -> "CapabilityState":
        """Lower authority only; no state update may self-escalate authority."""

        if authority_level < 0 or authority_level > self.authority_level:
            raise ValueError("authority may only be attenuated")
        if not isinstance(receipt, SourceReceipt):
            raise TypeError("authority updates require a SourceReceipt")
        return replace(self, authority_level=authority_level, source_receipts=self.source_receipts + (receipt,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "modality": self.modality,
            "installed": self.installed,
            "configured": self.configured,
            "healthy": self.healthy,
            "authorized": self.authorized,
            "verified": self.verified,
            "available": self.available,
            "authority_level": self.authority_level,
            "authority_ceiling": self.authority_ceiling,
            "budget_remaining": self.budget_remaining,
            "verifier_ref": self.verifier_ref,
            "rollback_ref": self.rollback_ref,
            "owner_scope": self.owner_scope,
            "source_receipts": [item.to_dict() for item in self.source_receipts],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class SelfModelSnapshot:
    """Canonical, profile-scoped answer to what the agent can do now."""

    profile_id: str
    tenant_id: str
    identity_ref: str
    capabilities: tuple[CapabilityState, ...]
    budgets: Mapping[str, int]
    active_providers: tuple[str, ...] = field(default_factory=tuple)
    degraded_modalities: tuple[str, ...] = field(default_factory=tuple)
    known_limitations: tuple[str, ...] = field(default_factory=tuple)
    snapshot_receipt: SourceReceipt | None = None
    schema: str = SELF_MODEL_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _clean(self.profile_id, "profile_id"))
        object.__setattr__(self, "tenant_id", _clean(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "identity_ref", _clean(self.identity_ref, "identity_ref"))
        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.capability_id))
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise ValueError("capability ids must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        budgets = _safe_mapping(self.budgets, "budgets")
        if any(not isinstance(value, int) or value < 0 for value in budgets.values()):
            raise ValueError("budgets must contain non-negative integer values")
        object.__setattr__(self, "budgets", budgets)
        object.__setattr__(self, "active_providers", _sorted_strings(self.active_providers, "provider"))
        object.__setattr__(self, "degraded_modalities", _sorted_strings(self.degraded_modalities, "modality"))
        object.__setattr__(self, "known_limitations", _sorted_strings(self.known_limitations, "limitation"))
        if self.snapshot_receipt is not None and not isinstance(self.snapshot_receipt, SourceReceipt):
            raise TypeError("snapshot_receipt must be a SourceReceipt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "profile_id": self.profile_id,
            "tenant_id": self.tenant_id,
            "identity_ref": self.identity_ref,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "budgets": dict(self.budgets),
            "active_providers": list(self.active_providers),
            "degraded_modalities": list(self.degraded_modalities),
            "known_limitations": list(self.known_limitations),
            "snapshot_receipt": self.snapshot_receipt.to_dict() if self.snapshot_receipt else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def transition(self, capability_id: str, healthy: bool, receipt: SourceReceipt, reason: str) -> tuple["SelfModelSnapshot", CapabilityTransition]:
        """Apply a measured loss/recovery and return its typed transition."""

        capability_id = _clean(capability_id, "capability_id")
        current = next((item for item in self.capabilities if item.capability_id == capability_id), None)
        if current is None:
            raise KeyError(capability_id)
        if current.healthy == healthy:
            raise ValueError("health transition does not change state")
        updated = current.with_health(healthy, receipt, reason)
        capabilities = tuple(updated if item.capability_id == capability_id else item for item in self.capabilities)
        degraded = set(self.degraded_modalities)
        if healthy:
            degraded.discard(current.modality)
        else:
            degraded.add(current.modality)
        return replace(self, capabilities=capabilities, degraded_modalities=tuple(degraded)), (CapabilityTransition.RECOVERY if healthy else CapabilityTransition.LOSS)


def build_snapshot(
    *,
    profile_id: str,
    tenant_id: str,
    identity_ref: str,
    capabilities: Iterable[CapabilityState],
    budgets: Mapping[str, int],
    snapshot_receipt: SourceReceipt,
    active_providers: Iterable[str] = (),
) -> SelfModelSnapshot:
    """Materialize a snapshot from caller-supplied authoritative receipts."""

    if not isinstance(snapshot_receipt, SourceReceipt):
        raise TypeError("snapshot_receipt is required")
    states = tuple(capabilities)
    degraded = tuple(state.modality for state in states if not state.available)
    limitations = tuple(limit for state in states for limit in state.limitations)
    return SelfModelSnapshot(
        profile_id=profile_id,
        tenant_id=tenant_id,
        identity_ref=identity_ref,
        capabilities=states,
        budgets=budgets,
        active_providers=tuple(active_providers),
        degraded_modalities=degraded,
        known_limitations=limitations,
        snapshot_receipt=snapshot_receipt,
    )


__all__ = [
    "SELF_MODEL_SCHEMA",
    "EvidenceClass",
    "CapabilityStatus",
    "CapabilityTransition",
    "SourceReceipt",
    "CapabilityState",
    "SelfModelSnapshot",
    "build_snapshot",
]
