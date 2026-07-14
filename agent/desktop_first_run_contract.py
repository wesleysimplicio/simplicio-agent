"""Bounded, additive Desktop first-run contract for issue #132.

This module models guided setup, recovery, and receipt-gated readiness without
performing any Desktop, filesystem, network, credential, or process operation.
Google OAuth and Stripe billing are default-off and unsafe settings fail closed.
It is a policy/state contract only; it is not proof of working Desktop E2E.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Mapping


ISSUE_NUMBER: Final = 132
DESKTOP_FIRST_RUN_SCHEMA: Final = "simplicio.desktop-first-run-contract"
DESKTOP_FIRST_RUN_VERSION: Final = "simplicio.desktop-first-run-contract/v1"
DEFAULT_OFF_INTEGRATIONS: Final = ("google", "stripe")
REQUIRED_PERMISSIONS: Final = frozenset({"workspace", "terminal"})
REQUIRED_RECEIPT_KINDS: Final = (
    "bootstrap",
    "handshake",
    "migrations",
    "neural_db",
    "smoke",
    "first_task",
)


class FirstRunState(StrEnum):
    """Persistable states; no state implies readiness by itself."""

    FRESH = "fresh"
    CHECKING = "checking"
    NEEDS_RUNTIME = "needs_runtime"
    NEEDS_MODEL = "needs_model"
    NEEDS_PROVIDER = "needs_provider"
    READY = "ready"
    DEGRADED = "degraded"
    REPAIRING = "repairing"
    FAILED = "failed"
    BLOCKED = "blocked"


class ModelMode(StrEnum):
    """The explicit model choice presented by guided setup."""

    LOCAL = "local"
    REMOTE = "remote"
    LATER = "later"


class ReadinessStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"


class BlockReason(StrEnum):
    """Stable, non-secret causes that keep first run from being ready."""

    UNSAFE_DEFAULTS = "unsafe_defaults"
    INVALID_RECEIPT = "invalid_receipt"
    RUNTIME_MISSING = "runtime_missing"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    MODEL_MISSING = "model_missing"
    PROVIDER_MISSING = "provider_missing"
    PERMISSIONS_MISSING = "permissions_missing"
    WORKSPACE_MISSING = "workspace_missing"
    READINESS_INCOMPLETE = "readiness_incomplete"
    INTERRUPTED = "interrupted"
    CORRUPT_STATE = "corrupt_state"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FirstRunPolicy:
    """Production-safe defaults for integrations and credential handling."""

    google_enabled: bool = False
    stripe_enabled: bool = False
    allow_plaintext_credentials: bool = False

    @property
    def is_safe(self) -> bool:
        return not self.violations()

    def violations(self) -> tuple[BlockReason, ...]:
        violations: list[BlockReason] = []
        if self.google_enabled or self.stripe_enabled or self.allow_plaintext_credentials:
            violations.append(BlockReason.UNSAFE_DEFAULTS)
        return tuple(violations)

    def to_dict(self) -> dict[str, bool]:
        return {
            "google_enabled": self.google_enabled,
            "stripe_enabled": self.stripe_enabled,
            "allow_plaintext_credentials": self.allow_plaintext_credentials,
        }


@dataclass(frozen=True, slots=True)
class FirstRunReceipt:
    """A bounded receipt reference; raw output and secrets are not stored."""

    kind: str
    id: str
    transaction_id: str
    evidence_ref: str
    ok: bool = True

    @property
    def is_valid(self) -> bool:
        return all(
            isinstance(value, str) and bool(value.strip())
            for value in (self.kind, self.id, self.transaction_id, self.evidence_ref)
        ) and isinstance(self.ok, bool) and self.ok

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "id": self.id,
            "transaction_id": self.transaction_id,
            "evidence_ref": self.evidence_ref,
            "ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class SetupSelection:
    """Explicit guided-setup selections, with a handle instead of a secret."""

    model: ModelMode | None = None
    provider: str | None = None
    workspace: str | None = None
    permissions: frozenset[str] = frozenset()
    secret_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", frozenset(self.permissions))

    @property
    def is_valid(self) -> bool:
        if not isinstance(self.model, ModelMode):
            return False
        if self.model is ModelMode.REMOTE:
            return _safe_handle(self.provider) and _safe_secret_handle(self.secret_ref)
        return not self.secret_ref or _safe_secret_handle(self.secret_ref)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model.value if isinstance(self.model, ModelMode) else None,
            "provider": self.provider,
            "workspace": self.workspace,
            "permissions": sorted(self.permissions),
            "secret_ref": self.secret_ref if _safe_secret_handle(self.secret_ref) else None,
        }


@dataclass(frozen=True, slots=True)
class ReadinessDecision:
    """A readiness result that exposes every blocking reason."""

    status: ReadinessStatus
    state: FirstRunState
    blockers: tuple[str, ...] = ()
    verified_receipts: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.status is ReadinessStatus.READY

    @property
    def is_blocked(self) -> bool:
        return not self.is_ready

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "state": self.state.value,
            "blockers": list(self.blockers),
            "verified_receipts": list(self.verified_receipts),
        }


@dataclass(frozen=True, slots=True)
class FirstRunSnapshot:
    """Serializable setup state; confirmed receipts survive interruption."""

    profile_id: str
    state: FirstRunState = FirstRunState.FRESH
    revision: int = 0
    selection: SetupSelection = field(default_factory=SetupSelection)
    policy: FirstRunPolicy = field(default_factory=FirstRunPolicy)
    receipts: tuple[FirstRunReceipt, ...] = ()
    reason: BlockReason | None = None
    next_action: str = "check"
    retryable: bool = True
    blocking: bool = True
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipts", tuple(self.receipts))

    @property
    def schema(self) -> str:
        return DESKTOP_FIRST_RUN_SCHEMA

    @property
    def schema_version(self) -> str:
        return DESKTOP_FIRST_RUN_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without turning state into proof."""

        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "issue": ISSUE_NUMBER,
            "profile_id": self.profile_id,
            "state": self.state.value,
            "revision": self.revision,
            "selection": self.selection.to_dict(),
            "policy": self.policy.to_dict(),
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "reason": self.reason.value if isinstance(self.reason, BlockReason) else None,
            "next_action": self.next_action,
            "retryable": self.retryable,
            "blocking": self.blocking,
            "transaction_id": self.transaction_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def create_first_run_snapshot(profile_id: str, *, policy: FirstRunPolicy | None = None) -> FirstRunSnapshot:
    """Create a fresh snapshot; invalid identity is rejected before use."""

    if not _safe_handle(profile_id):
        raise ValueError("profile_id must be a non-empty safe handle")
    return FirstRunSnapshot(profile_id=profile_id, policy=policy or FirstRunPolicy())


def evaluate_readiness(snapshot: FirstRunSnapshot) -> ReadinessDecision:
    """Evaluate the final gate; marker/process/provider presence is insufficient."""

    blockers: list[str] = []
    verified: list[str] = []
    blockers.extend(reason.value for reason in snapshot.policy.violations())

    if not isinstance(snapshot.state, FirstRunState):
        blockers.append(BlockReason.CORRUPT_STATE.value)
    if not snapshot.selection.is_valid:
        blockers.append(BlockReason.PROVIDER_MISSING.value)
    elif snapshot.selection.model is ModelMode.LATER:
        blockers.append(BlockReason.MODEL_MISSING.value)
    if not _safe_handle(snapshot.selection.workspace):
        blockers.append(BlockReason.WORKSPACE_MISSING.value)
    missing_permissions = sorted(REQUIRED_PERMISSIONS - snapshot.selection.permissions)
    if missing_permissions:
        blockers.append(f"{BlockReason.PERMISSIONS_MISSING.value}:{','.join(missing_permissions)}")

    receipts_by_kind: dict[str, FirstRunReceipt] = {}
    for receipt in snapshot.receipts:
        if receipt.kind in REQUIRED_RECEIPT_KINDS and receipt.is_valid and receipt.kind not in receipts_by_kind:
            receipts_by_kind[receipt.kind] = receipt
    for kind in REQUIRED_RECEIPT_KINDS:
        if kind in receipts_by_kind:
            verified.append(kind)
        else:
            blockers.append(f"missing_receipt:{kind}")

    if snapshot.state is not FirstRunState.READY:
        blockers.append(f"state:{snapshot.state.value}")
    if blockers:
        status = (
            ReadinessStatus.DEGRADED
            if snapshot.state is FirstRunState.DEGRADED
            else ReadinessStatus.BLOCKED
        )
        return ReadinessDecision(status, snapshot.state, tuple(dict.fromkeys(blockers)), tuple(verified))
    return ReadinessDecision(ReadinessStatus.READY, snapshot.state, (), tuple(verified))


def reduce_first_run(snapshot: FirstRunSnapshot, event: Mapping[str, object]) -> FirstRunSnapshot:
    """Apply one bounded event; malformed or unsafe events fail closed."""

    if not isinstance(event, Mapping):
        return _blocked(snapshot, BlockReason.UNKNOWN, "repair_state")
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return _blocked(snapshot, BlockReason.UNKNOWN, "repair_state")
    if not snapshot.policy.is_safe:
        return _blocked(snapshot, BlockReason.UNSAFE_DEFAULTS, "repair_policy")

    if event_type == "check_started":
        return _update(snapshot, state=FirstRunState.CHECKING, reason=None, next_action="verify_runtime")
    if event_type == "runtime_missing":
        reason = _enum_reason(event.get("reason"), BlockReason.RUNTIME_MISSING)
        return _update(
            snapshot,
            state=FirstRunState.NEEDS_RUNTIME,
            reason=reason,
            next_action="install_runtime",
            blocking=True,
        )
    if event_type == "model_selected":
        try:
            model = event["model"] if isinstance(event["model"], ModelMode) else ModelMode(event["model"])
        except (KeyError, TypeError, ValueError):
            return _blocked(snapshot, BlockReason.MODEL_MISSING, "select_model")
        selection = SetupSelection(
            model=model,
            provider=snapshot.selection.provider,
            workspace=snapshot.selection.workspace,
            permissions=snapshot.selection.permissions,
            secret_ref=snapshot.selection.secret_ref,
        )
        if model is ModelMode.LATER:
            return _update(
                snapshot,
                selection=selection,
                state=FirstRunState.DEGRADED,
                reason=BlockReason.MODEL_MISSING,
                next_action="select_model",
                blocking=False,
            )
        return _update(
            snapshot,
            selection=selection,
            state=FirstRunState.NEEDS_PROVIDER if model is ModelMode.REMOTE else FirstRunState.CHECKING,
            reason=BlockReason.PROVIDER_MISSING if model is ModelMode.REMOTE else None,
            next_action="select_provider" if model is ModelMode.REMOTE else "grant_permissions",
        )
    if event_type == "provider_selected":
        provider = event.get("provider")
        if not _safe_handle(provider):
            return _blocked(snapshot, BlockReason.PROVIDER_MISSING, "select_provider")
        secret_ref = event.get("secret_ref", snapshot.selection.secret_ref)
        if snapshot.selection.model is ModelMode.REMOTE and not _safe_secret_handle(secret_ref):
            return _update(
                snapshot,
                state=FirstRunState.NEEDS_PROVIDER,
                reason=BlockReason.PROVIDER_MISSING,
                next_action="store_provider_reference",
            )
        selection = _replace_selection(snapshot.selection, provider=provider, secret_ref=secret_ref)
        return _update(snapshot, selection=selection, state=FirstRunState.CHECKING, reason=None, next_action="grant_permissions")
    if event_type == "workspace_selected":
        workspace = event.get("workspace")
        if not _safe_handle(workspace):
            return _blocked(snapshot, BlockReason.WORKSPACE_MISSING, "select_workspace")
        return _update(snapshot, selection=_replace_selection(snapshot.selection, workspace=workspace), next_action="grant_permissions")
    if event_type == "permission_granted":
        permission = event.get("permission")
        if not _safe_handle(permission):
            return _blocked(snapshot, BlockReason.PERMISSIONS_MISSING, "grant_permissions")
        selection = _replace_selection(snapshot.selection, permissions=snapshot.selection.permissions | {permission})
        return _update(snapshot, selection=selection, next_action="verify_permissions")
    if event_type == "setup_later":
        selection = _replace_selection(snapshot.selection, model=ModelMode.LATER)
        return _update(
            snapshot,
            selection=selection,
            state=FirstRunState.DEGRADED,
            reason=BlockReason.MODEL_MISSING,
            next_action="select_model",
            blocking=False,
        )
    if event_type == "receipt":
        receipt = event.get("receipt")
        if not isinstance(receipt, FirstRunReceipt) or receipt.kind not in REQUIRED_RECEIPT_KINDS or not receipt.is_valid:
            return _blocked(snapshot, BlockReason.INVALID_RECEIPT, "collect_receipt")
        receipts = tuple(existing for existing in snapshot.receipts if existing.kind != receipt.kind) + (receipt,)
        candidate = _update(snapshot, receipts=receipts, transaction_id=receipt.transaction_id, state=FirstRunState.CHECKING, reason=None)
        if receipt.kind == "first_task":
            decision = evaluate_readiness(_update(candidate, state=FirstRunState.READY))
            if decision.is_ready:
                return _update(candidate, state=FirstRunState.READY, blocking=False, retryable=False, next_action="open_app")
            return _blocked(candidate, BlockReason.READINESS_INCOMPLETE, "complete_activation")
        return _update(candidate, next_action=_next_action_for_receipt(receipt.kind))
    if event_type == "repair_started":
        return _update(snapshot, state=FirstRunState.REPAIRING, reason=None, next_action="repair", blocking=True)
    if event_type == "failed":
        return _update(snapshot, state=FirstRunState.FAILED, reason=_enum_reason(event.get("reason"), BlockReason.UNKNOWN), next_action="retry")
    if event_type == "reset":
        return create_first_run_snapshot(snapshot.profile_id, policy=snapshot.policy)
    return _blocked(snapshot, BlockReason.UNKNOWN, "repair_state")


def resume_first_run(snapshot: FirstRunSnapshot) -> FirstRunSnapshot:
    """Resume interrupted work while retaining only valid confirmed receipts."""

    valid_receipts = tuple(receipt for receipt in snapshot.receipts if receipt.is_valid)
    repaired = _update(snapshot, receipts=valid_receipts)
    if snapshot.state is FirstRunState.READY and not evaluate_readiness(repaired).is_ready:
        return _update(repaired, state=FirstRunState.REPAIRING, reason=BlockReason.CORRUPT_STATE, next_action="repair", blocking=True)
    if snapshot.state in (FirstRunState.CHECKING, FirstRunState.REPAIRING, FirstRunState.FAILED, FirstRunState.BLOCKED):
        return _update(repaired, state=FirstRunState.CHECKING, reason=BlockReason.INTERRUPTED, next_action="resume_transaction", blocking=True)
    return repaired


def parse_first_run_snapshot(value: object) -> FirstRunSnapshot | None:
    """Parse shape only; callers must still call ``resume_first_run``/readiness."""

    if not isinstance(value, Mapping) or value.get("schema") != DESKTOP_FIRST_RUN_SCHEMA:
        return None
    try:
        profile_id = value["profile_id"]
        state = FirstRunState(value["state"])
        selection_data = value.get("selection", {})
        policy_data = value.get("policy", {})
        receipts_data = value.get("receipts", [])
        if not isinstance(profile_id, str) or not isinstance(selection_data, Mapping) or not isinstance(policy_data, Mapping) or not isinstance(receipts_data, list):
            return None
        selection = SetupSelection(
            model=ModelMode(selection_data["model"]) if selection_data.get("model") is not None else None,
            provider=selection_data.get("provider"),
            workspace=selection_data.get("workspace"),
            permissions=frozenset(selection_data.get("permissions", [])),
            secret_ref=selection_data.get("secret_ref"),
        )
        policy = FirstRunPolicy(
            google_enabled=policy_data.get("google_enabled", False),
            stripe_enabled=policy_data.get("stripe_enabled", False),
            allow_plaintext_credentials=policy_data.get("allow_plaintext_credentials", False),
        )
        receipts = tuple(
            FirstRunReceipt(
                kind=item["kind"],
                id=item["id"],
                transaction_id=item["transaction_id"],
                evidence_ref=item["evidence_ref"],
                ok=item.get("ok", False),
            )
            for item in receipts_data
            if isinstance(item, Mapping)
        )
        return FirstRunSnapshot(
            profile_id=profile_id,
            state=state,
            revision=value.get("revision", 0),
            selection=selection,
            policy=policy,
            receipts=receipts,
            reason=BlockReason(value["reason"]) if value.get("reason") is not None else None,
            next_action=value.get("next_action", "check"),
            retryable=value.get("retryable", True),
            blocking=value.get("blocking", True),
            transaction_id=value.get("transaction_id"),
        )
    except (KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class DesktopFirstRunContract:
    """Small facade for callers that want a policy-scoped contract object."""

    policy: FirstRunPolicy = field(default_factory=FirstRunPolicy)

    @property
    def is_safe(self) -> bool:
        return self.policy.is_safe

    def create(self, profile_id: str) -> FirstRunSnapshot:
        return create_first_run_snapshot(profile_id, policy=self.policy)

    def reduce(self, snapshot: FirstRunSnapshot, event: Mapping[str, object]) -> FirstRunSnapshot:
        return reduce_first_run(snapshot, event)

    def readiness(self, snapshot: FirstRunSnapshot) -> ReadinessDecision:
        return evaluate_readiness(snapshot)


def _safe_handle(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _safe_secret_handle(value: object) -> bool:
    return _safe_handle(value) and value.strip().lower().startswith(("vault://", "keychain://"))


def _replace_selection(selection: SetupSelection, **changes: object) -> SetupSelection:
    values = {
        "model": selection.model,
        "provider": selection.provider,
        "workspace": selection.workspace,
        "permissions": selection.permissions,
        "secret_ref": selection.secret_ref,
    }
    values.update(changes)
    return SetupSelection(**values)


def _enum_reason(value: object, default: BlockReason) -> BlockReason:
    try:
        return value if isinstance(value, BlockReason) else BlockReason(value)
    except (TypeError, ValueError):
        return default


def _next_action_for_receipt(kind: str) -> str:
    return {
        "bootstrap": "verify_handshake",
        "handshake": "verify_migrations",
        "migrations": "verify_neural_db",
        "neural_db": "run_smoke",
        "smoke": "run_first_task",
    }.get(kind, "complete_activation")


def _update(snapshot: FirstRunSnapshot, **changes: object) -> FirstRunSnapshot:
    values = {
        "profile_id": snapshot.profile_id,
        "state": snapshot.state,
        "revision": snapshot.revision + 1,
        "selection": snapshot.selection,
        "policy": snapshot.policy,
        "receipts": snapshot.receipts,
        "reason": snapshot.reason,
        "next_action": snapshot.next_action,
        "retryable": snapshot.retryable,
        "blocking": snapshot.blocking,
        "transaction_id": snapshot.transaction_id,
    }
    values.update(changes)
    return FirstRunSnapshot(**values)


def _blocked(snapshot: FirstRunSnapshot, reason: BlockReason, next_action: str) -> FirstRunSnapshot:
    return _update(
        snapshot,
        state=FirstRunState.BLOCKED,
        reason=reason,
        next_action=next_action,
        blocking=True,
        retryable=True,
    )


__all__ = [
    "BlockReason",
    "DEFAULT_OFF_INTEGRATIONS",
    "DESKTOP_FIRST_RUN_SCHEMA",
    "DESKTOP_FIRST_RUN_VERSION",
    "DesktopFirstRunContract",
    "FirstRunPolicy",
    "FirstRunReceipt",
    "FirstRunSnapshot",
    "FirstRunState",
    "ISSUE_NUMBER",
    "ModelMode",
    "REQUIRED_PERMISSIONS",
    "REQUIRED_RECEIPT_KINDS",
    "ReadinessDecision",
    "ReadinessStatus",
    "SetupSelection",
    "create_first_run_snapshot",
    "evaluate_readiness",
    "parse_first_run_snapshot",
    "reduce_first_run",
    "resume_first_run",
]
