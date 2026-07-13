"""Versioned machine-readable contracts for agent/runtime capability exchange.

This module is intentionally transport-agnostic.  It defines stable identities
for the shipped product and its agent/runtime components, a schema-producer
capability envelope, helpers for compatibility reporting, and a legacy upcaster
that normalizes pre-versioned payloads into the current contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

PRODUCT_SCHEMA = "machine-contracts/product/v1"
COMPONENT_SCHEMA = "machine-contracts/component/v1"
ENVELOPE_SCHEMA = "machine-contracts/capability-envelope/v1"
RECEIPT_SCHEMA = "machine-contracts/receipt-metadata/v1"
MATRIX_SCHEMA = "machine-contracts/compatibility-matrix/v1"
LEGACY_SCHEMAS = frozenset({"machine_contract", "machine-contract", "legacy-machine-contract"})
CURRENT_CONTRACT_VERSION = 1


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _as_version_triplet(version: str) -> tuple[int, int, int]:
    parts = _trim(version).split(".")
    parsed: list[int] = []
    for index in range(3):
        try:
            parsed.append(int(parts[index]))
        except (IndexError, ValueError):
            parsed.append(0)
    return tuple(parsed)


@dataclass(frozen=True)
class SchemaProducerEnvelope:
    """Declares what schema family a component can emit and accept."""

    producer: str
    schema_family: str
    produced_version: int
    min_consumer_version: int = 1
    max_consumer_version: int = 1
    features: tuple[str, ...] = ()
    schema: str = ENVELOPE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["features"] = list(self.features)
        return data


@dataclass(frozen=True)
class ProductIdentity:
    """Stable identity for the shipped product surface."""

    product: str
    version: str
    surface: str = "simplicio-agent"
    role: str = "agent_product"
    schema: str = PRODUCT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComponentIdentity:
    """Stable identity for one machine-facing component within the product."""

    name: str
    version: str
    role: str
    boundary: str
    capability_envelope: SchemaProducerEnvelope
    schema: str = COMPONENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capability_envelope"] = self.capability_envelope.to_dict()
        return data


@dataclass(frozen=True)
class MachineContract:
    """Top-level contract exchanged between agent/runtime participants."""

    product: ProductIdentity
    agent: ComponentIdentity
    runtime: ComponentIdentity
    compatibility: dict[str, Any]
    contract_version: int = CURRENT_CONTRACT_VERSION
    schema: str = PRODUCT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "product": self.product.to_dict(),
            "agent": self.agent.to_dict(),
            "runtime": self.runtime.to_dict(),
            "compatibility": dict(self.compatibility),
        }


@dataclass(frozen=True)
class ReceiptMetadata:
    """Receipt metadata safe to attach to logs, ledgers, and diagnostics."""

    request_id: str
    transport: str
    redaction_applied: bool
    schema: str = RECEIPT_SCHEMA
    actor: str | None = None
    path: str | None = None
    environment: str | None = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["raw_metadata"] = dict(self.raw_metadata)
        return result

    def redacted(self) -> dict[str, Any]:
        result = self.to_dict()
        result["path"] = _redact_text(self.path)
        result["environment"] = _redact_text(self.environment)
        result["raw_metadata"] = {
            key: _redact_value(key, value) for key, value in self.raw_metadata.items()
        }
        result["redaction_applied"] = True
        return result


def _redact_text(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    return "[redacted]"


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("path", "token", "secret", "key", "env")):
        return "[redacted]"
    return value


def make_product_identity(version: str, *, surface: str = "simplicio-agent") -> ProductIdentity:
    return ProductIdentity(product="Simplicio Agent", version=version, surface=surface)


def make_component_identity(
    name: str,
    version: str,
    *,
    role: str,
    boundary: str,
    produced_version: int = CURRENT_CONTRACT_VERSION,
    min_consumer_version: int = 1,
    max_consumer_version: int = CURRENT_CONTRACT_VERSION,
    features: tuple[str, ...] = (),
) -> ComponentIdentity:
    return ComponentIdentity(
        name=name,
        version=version,
        role=role,
        boundary=boundary,
        capability_envelope=SchemaProducerEnvelope(
            producer=name,
            schema_family="machine-contracts",
            produced_version=produced_version,
            min_consumer_version=min_consumer_version,
            max_consumer_version=max_consumer_version,
            features=features,
        ),
    )


def build_machine_contract(
    *,
    product_version: str,
    agent_version: str,
    runtime_version: str,
    agent_features: tuple[str, ...] = (),
    runtime_features: tuple[str, ...] = (),
) -> MachineContract:
    product = make_product_identity(product_version)
    agent = make_component_identity(
        "simplicio-agent",
        agent_version,
        role="agent",
        boundary="orchestration",
        features=agent_features,
    )
    runtime = make_component_identity(
        "simplicio-runtime",
        runtime_version,
        role="runtime",
        boundary="deterministic_kernel",
        features=runtime_features,
    )
    compatibility = compatibility_report(agent=agent, runtime=runtime)
    return MachineContract(
        product=product,
        agent=agent,
        runtime=runtime,
        compatibility=compatibility,
    )


def compatibility_report(
    *, agent: ComponentIdentity, runtime: ComponentIdentity
) -> dict[str, Any]:
    agent_version = _as_version_triplet(agent.version)
    runtime_version = _as_version_triplet(runtime.version)
    major_match = agent_version[0] == runtime_version[0]
    envelope_overlap = not (
        agent.capability_envelope.min_consumer_version
        > runtime.capability_envelope.produced_version
        or runtime.capability_envelope.min_consumer_version
        > agent.capability_envelope.produced_version
    )
    compatible = major_match and envelope_overlap
    reasons = []
    if not major_match:
        reasons.append("major_version_mismatch")
    if not envelope_overlap:
        reasons.append("schema_version_window_mismatch")
    if not reasons:
        reasons.append("compatible")
    return {
        "schema": MATRIX_SCHEMA,
        "compatible": compatible,
        "reasons": reasons,
        "agent_version": agent.version,
        "runtime_version": runtime.version,
        "agent_schema_version": agent.capability_envelope.produced_version,
        "runtime_schema_version": runtime.capability_envelope.produced_version,
    }


def compatibility_row(
    *, agent_version: str, runtime_version: str, expected: str
) -> dict[str, str]:
    return {
        "agent_version": agent_version,
        "runtime_version": runtime_version,
        "expected": expected,
    }


def compatibility_matrix(rows: list[dict[str, str]]) -> dict[str, Any]:
    normalized = []
    for row in rows:
        normalized.append(
            compatibility_row(
                agent_version=str(row["agent_version"]),
                runtime_version=str(row["runtime_version"]),
                expected=str(row["expected"]),
            )
        )
    return {"schema": MATRIX_SCHEMA, "rows": normalized}


def upcast_legacy_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy machine-contract payloads into the current layout."""

    schema = str(payload.get("schema", ""))
    if schema == PRODUCT_SCHEMA and int(payload.get("contract_version", 0) or 0) >= 1:
        return dict(payload)
    if schema and schema not in LEGACY_SCHEMAS:
        raise ValueError(f"unsupported machine contract schema: {schema}")

    product_version = str(
        payload.get("product_version")
        or payload.get("version")
        or payload.get("agent_version")
        or "0.0.0"
    )
    agent_version = str(payload.get("agent_version") or product_version)
    runtime_version = str(
        payload.get("runtime_version") or payload.get("kernel_version") or "0.0.0"
    )
    legacy_features = tuple(payload.get("features") or ())
    runtime_features = tuple(payload.get("runtime_features") or ())
    contract = build_machine_contract(
        product_version=product_version,
        agent_version=agent_version,
        runtime_version=runtime_version,
        agent_features=legacy_features,
        runtime_features=runtime_features,
    ).to_dict()
    contract["legacy_source_schema"] = schema or "machine_contract"
    contract["legacy_adapter"] = {
        "upcast_from": schema or "machine_contract",
        "upcast_to": PRODUCT_SCHEMA,
    }
    return contract


__all__ = [
    "COMPONENT_SCHEMA",
    "CURRENT_CONTRACT_VERSION",
    "ENVELOPE_SCHEMA",
    "LEGACY_SCHEMAS",
    "MATRIX_SCHEMA",
    "PRODUCT_SCHEMA",
    "RECEIPT_SCHEMA",
    "ComponentIdentity",
    "MachineContract",
    "ProductIdentity",
    "ReceiptMetadata",
    "SchemaProducerEnvelope",
    "build_machine_contract",
    "compatibility_matrix",
    "compatibility_report",
    "compatibility_row",
    "make_component_identity",
    "make_product_identity",
    "upcast_legacy_contract",
]
