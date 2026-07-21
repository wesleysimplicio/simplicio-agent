"""Project existing registry/runtime/policy facts into the #168 self-model.

This module is an adapter, not a runtime implementation.  It consumes the
already measured ``CapabilityRegistry`` and a caller-supplied Simplicio Runtime
health report, then materializes the existing immutable self-model contract.
Missing or malformed policy inputs fail closed; no capability is inferred from
model text or from a tool/page response.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from agent.capability_registry import CapabilityRegistry, Health
from agent.self_model import CapabilityState, SelfModelSnapshot, SourceReceipt, build_snapshot


PROJECTION_SCHEMA = "simplicio.self-model-projection/v1"


def _required_bool(values: Mapping[str, bool], capability_id: str, field_name: str) -> bool:
    if capability_id not in values:
        raise ValueError(f"{field_name} is missing for {capability_id}")
    value = values[capability_id]
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool for {capability_id}")
    return value


def _required_int(values: Mapping[str, int], capability_id: str, field_name: str) -> int:
    if capability_id not in values:
        raise ValueError(f"{field_name} is missing for {capability_id}")
    value = values[capability_id]
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int for {capability_id}")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative for {capability_id}")
    return value


def _required_text(values: Mapping[str, str], capability_id: str, field_name: str) -> str:
    if capability_id not in values:
        raise ValueError(f"{field_name} is missing for {capability_id}")
    value = values[capability_id]
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string for {capability_id}")
    return value.strip()


def _runtime_healthy(report: Mapping[str, Any]) -> bool:
    """Read the measured boolean only; status strings are not evidence."""

    value = report.get("healthy")
    if type(value) is not bool:
        raise ValueError("runtime health report must contain a measured boolean")
    return value


def project_registry(
    registry: CapabilityRegistry,
    runtime_health: Mapping[str, Any],
    *,
    profile_id: str,
    tenant_id: str,
    identity_ref: str,
    configured: Mapping[str, bool],
    authorized: Mapping[str, bool],
    verified: Mapping[str, bool],
    authority_levels: Mapping[str, int],
    authority_ceilings: Mapping[str, int],
    budget_remaining: Mapping[str, int],
    budgets: Mapping[str, int],
    verifier_refs: Mapping[str, str],
    rollback_refs: Mapping[str, str],
    owner_scopes: Mapping[str, str],
    runtime_receipt: SourceReceipt,
    policy_receipt: SourceReceipt,
    snapshot_receipt: SourceReceipt,
    authority_attenuations: Mapping[str, int] | None = None,
    active_providers: Iterable[str] = (),
) -> SelfModelSnapshot:
    """Build a self-model from registry, runtime health, and policy facts.

    ``authority_attenuations`` represents an already-authorized subagent or
    provider envelope.  It may only lower the policy level.  Runtime health is
    a global execution gate for registered capabilities: if the runtime is not
    measured healthy, every capability remains visible but unavailable.
    """

    if not isinstance(registry, CapabilityRegistry):
        raise TypeError("registry must be a CapabilityRegistry")
    for name, receipt in (
        ("runtime_receipt", runtime_receipt),
        ("policy_receipt", policy_receipt),
        ("snapshot_receipt", snapshot_receipt),
    ):
        if not isinstance(receipt, SourceReceipt):
            raise TypeError(f"{name} must be a SourceReceipt")

    runtime_is_healthy = _runtime_healthy(runtime_health)
    attenuations = authority_attenuations or {}
    states: list[CapabilityState] = []
    for capability in registry.list():
        capability_id = capability.id
        policy_configured = _required_bool(configured, capability_id, "configured")
        is_authorized = _required_bool(authorized, capability_id, "authorized")
        is_verified = _required_bool(verified, capability_id, "verified")
        authority_level = _required_int(authority_levels, capability_id, "authority_level")
        authority_ceiling = _required_int(
            authority_ceilings, capability_id, "authority_ceiling"
        )
        remaining = _required_int(budget_remaining, capability_id, "budget_remaining")
        verifier_ref = _required_text(verifier_refs, capability_id, "verifier_ref")
        rollback_ref = _required_text(rollback_refs, capability_id, "rollback_ref")
        owner_scope = _required_text(owner_scopes, capability_id, "owner_scope")

        # The registry proves installation; the explicit policy input proves
        # configuration.  A disabled registry entry cannot be configured for
        # execution even if stale policy says otherwise.
        configured_now = policy_configured and capability.enabled
        healthy_now = runtime_is_healthy and capability.metadata.health is Health.HEALTHY
        limitations: list[str] = []
        if not runtime_is_healthy:
            limitations.append("simplicio-runtime health is not ready")
        if capability.metadata.health is not Health.HEALTHY:
            limitations.append(f"registry health is {capability.metadata.health.value}")
        if not capability.enabled:
            limitations.append("capability is disabled by registry policy")
        if not configured_now:
            limitations.append("capability is not configured")
        if not is_authorized:
            limitations.append("capability is not authorized")
        if not is_verified:
            limitations.append("actuator verification is unavailable")
        if remaining == 0:
            limitations.append("capability budget is exhausted")

        state = CapabilityState(
            capability_id=capability_id,
            modality=capability.metadata.source,
            installed=True,
            configured=configured_now,
            healthy=healthy_now,
            authorized=is_authorized,
            verified=is_verified,
            authority_level=authority_level,
            authority_ceiling=authority_ceiling,
            budget_remaining=remaining,
            verifier_ref=verifier_ref,
            rollback_ref=rollback_ref,
            owner_scope=owner_scope if is_authorized else "",
            source_receipts=(runtime_receipt, policy_receipt),
            limitations=tuple(limitations),
        )
        if capability_id in attenuations:
            state = state.attenuate(
                _required_int(attenuations, capability_id, "authority_attenuation"),
                policy_receipt,
            )
        states.append(state)

    return build_snapshot(
        profile_id=profile_id,
        tenant_id=tenant_id,
        identity_ref=identity_ref,
        capabilities=states,
        budgets=budgets,
        snapshot_receipt=snapshot_receipt,
        active_providers=active_providers,
    )


__all__ = ["PROJECTION_SCHEMA", "project_registry"]
