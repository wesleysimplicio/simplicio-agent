"""Bounded, per-host MCP/CLI compatibility certificates.

The certificate is intentionally additive and local to one host.  It proves
only the checks supplied by its caller; it is not a multi-host certification
matrix and it never treats an unavailable MCP path as silently healthy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
READY = "ready"
FALLBACK_READY = "fallback_ready"
NOT_READY = "not_ready"


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _hash_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class HostProviderVersion:
    """Identity of the single host covered by a certificate."""

    host: str
    provider: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "host": self.host,
            "provider": self.provider,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class CommandCheck:
    """Result of one CLI command compatibility check."""

    name: str
    command: str
    passed: bool
    evidence: str
    exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "passed": self.passed,
            "evidence": self.evidence,
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True, slots=True)
class MCPCheck:
    """Result of one MCP lifecycle or capability check."""

    name: str
    method: str
    passed: bool
    evidence: str
    transport: str = "stdio"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "passed": self.passed,
            "evidence": self.evidence,
            "transport": self.transport,
        }


@dataclass(frozen=True, slots=True)
class Fallback:
    """Explicit fallback selection; ``none`` is the default MCP path."""

    mode: str = "none"
    command: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "mode": self.mode,
            "command": self.command,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CertificateValidation:
    """Structured validation result; all invalid states remain fail-closed."""

    valid: bool
    ready: bool
    reasons: tuple[str, ...]
    evidence_hash: str | None
    readiness: str


@dataclass(frozen=True, slots=True)
class CompatibilityCertificate:
    """A bounded certificate for exactly one host/provider/version tuple."""

    schema_version: int
    identity: HostProviderVersion
    command_checks: tuple[CommandCheck, ...]
    mcp_checks: tuple[MCPCheck, ...]
    fallback: Fallback
    readiness: str
    evidence_hash: str

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "command_checks": [check.to_dict() for check in self.command_checks],
            "mcp_checks": [check.to_dict() for check in self.mcp_checks],
            "fallback": self.fallback.to_dict(),
            "readiness": self.readiness,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["evidence_hash"] = self.evidence_hash
        return payload

    def validate(self) -> CertificateValidation:
        return validate_certificate(self)

    def is_ready(self) -> bool:
        return self.validate().ready

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CompatibilityCertificate:
        return from_dict(data)


def _check_fields(
    checks: Sequence[object],
    *,
    kind: str,
) -> list[str]:
    reasons: list[str] = []
    for index, check in enumerate(checks):
        prefix = f"{kind}_check_{index}"
        if kind == "command" and isinstance(check, CommandCheck):
            fields = (check.name, check.command, check.evidence)
            if not all(_nonblank(field) for field in fields):
                reasons.append(f"{prefix}_missing_required_field")
            if type(check.passed) is not bool:
                reasons.append(f"{prefix}_invalid_passed")
            if check.exit_code is not None and type(check.exit_code) is not int:
                reasons.append(f"{prefix}_invalid_exit_code")
            elif check.exit_code is not None and check.passed != (check.exit_code == 0):
                reasons.append(f"{prefix}_exit_code_mismatch")
        elif kind == "mcp" and isinstance(check, MCPCheck):
            fields = (check.name, check.method, check.transport, check.evidence)
            if not all(_nonblank(field) for field in fields):
                reasons.append(f"{prefix}_missing_required_field")
            if type(check.passed) is not bool:
                reasons.append(f"{prefix}_invalid_passed")
        else:
            reasons.append(f"{prefix}_malformed")
    return reasons


def _readiness_for(
    certificate: CompatibilityCertificate,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    identity = certificate.identity
    if not isinstance(identity, HostProviderVersion):
        reasons.append("missing_identity")
    elif not all(
        _nonblank(value) for value in (identity.host, identity.provider, identity.version)
    ):
        reasons.append("missing_identity_field")

    if not certificate.command_checks:
        reasons.append("missing_command_checks")
    else:
        reasons.extend(_check_fields(certificate.command_checks, kind="command"))
    if not certificate.mcp_checks:
        reasons.append("missing_mcp_checks")
    else:
        reasons.extend(_check_fields(certificate.mcp_checks, kind="mcp"))

    fallback = certificate.fallback
    if not isinstance(fallback, Fallback):
        reasons.append("malformed_fallback")
        return NOT_READY, reasons
    if fallback.mode not in {"none", "cli"}:
        reasons.append("unknown_fallback_mode")
    if fallback.mode == "none" and (fallback.command is not None or fallback.reason is not None):
        reasons.append("implicit_fallback_not_allowed")
    if fallback.mode == "cli":
        if not _nonblank(fallback.command) or not _nonblank(fallback.reason):
            reasons.append("incomplete_cli_fallback")
        elif not any(
            check.passed and check.command == fallback.command
            for check in certificate.command_checks
            if isinstance(check, CommandCheck)
        ):
            reasons.append("fallback_command_not_proven")

    command_passed = bool(certificate.command_checks) and all(
        isinstance(check, CommandCheck) and check.passed
        for check in certificate.command_checks
    )
    mcp_passed = bool(certificate.mcp_checks) and all(
        isinstance(check, MCPCheck) and check.passed for check in certificate.mcp_checks
    )
    mcp_failed = bool(certificate.mcp_checks) and any(
        isinstance(check, MCPCheck) and not check.passed for check in certificate.mcp_checks
    )

    if fallback.mode == "cli":
        if not mcp_failed:
            reasons.append("fallback_requires_failed_mcp_check")
        if not command_passed:
            reasons.append("fallback_requires_passing_cli_checks")
        if not reasons:
            return FALLBACK_READY, []
    elif not command_passed:
        reasons.append("failed_command_check")
    elif not mcp_passed:
        reasons.append("failed_mcp_check")
    elif not reasons:
        return READY, []

    return NOT_READY, reasons if reasons else ["not_ready"]


def compute_evidence_hash(certificate: CompatibilityCertificate) -> str:
    """Return the canonical SHA-256 for certificate content without its hash."""

    return _hash_payload(certificate._payload())


def validate_certificate(certificate: object) -> CertificateValidation:
    """Validate a certificate without trusting its claimed readiness or hash."""

    if not isinstance(certificate, CompatibilityCertificate):
        return CertificateValidation(False, False, ("malformed_certificate",), None, NOT_READY)

    readiness, reasons = _readiness_for(certificate)
    if certificate.schema_version != SCHEMA_VERSION:
        reasons.append("unsupported_schema_version")
    if certificate.readiness not in {READY, FALLBACK_READY, NOT_READY}:
        reasons.append("unknown_readiness")
    if certificate.readiness != readiness:
        reasons.append("readiness_mismatch")

    expected_hash = compute_evidence_hash(certificate)
    if certificate.evidence_hash != expected_hash:
        reasons.append("evidence_hash_mismatch")

    valid = not reasons
    ready = valid and readiness in {READY, FALLBACK_READY}
    return CertificateValidation(
        valid,
        ready,
        tuple(dict.fromkeys(reasons)),
        expected_hash,
        readiness if valid else NOT_READY,
    )


def build_certificate(
    *,
    host: str,
    provider: str,
    version: str,
    command_checks: Sequence[CommandCheck],
    mcp_checks: Sequence[MCPCheck],
    fallback: Fallback | None = None,
) -> CompatibilityCertificate:
    """Build a certificate and derive readiness plus its evidence hash."""

    candidate = CompatibilityCertificate(
        schema_version=SCHEMA_VERSION,
        identity=HostProviderVersion(host, provider, version),
        command_checks=tuple(command_checks),
        mcp_checks=tuple(mcp_checks),
        fallback=fallback or Fallback(),
        readiness=NOT_READY,
        evidence_hash="",
    )
    readiness, _ = _readiness_for(candidate)
    candidate = CompatibilityCertificate(
        schema_version=candidate.schema_version,
        identity=candidate.identity,
        command_checks=candidate.command_checks,
        mcp_checks=candidate.mcp_checks,
        fallback=candidate.fallback,
        readiness=readiness,
        evidence_hash="",
    )
    return CompatibilityCertificate(
        schema_version=candidate.schema_version,
        identity=candidate.identity,
        command_checks=candidate.command_checks,
        mcp_checks=candidate.mcp_checks,
        fallback=candidate.fallback,
        readiness=candidate.readiness,
        evidence_hash=compute_evidence_hash(candidate),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _items(value: object) -> tuple[object, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (None,) if value is not None else ()


def from_dict(data: Mapping[str, Any]) -> CompatibilityCertificate:
    """Deserialize without trusting readiness or evidence hash fields."""

    identity_data = _mapping(data.get("identity")) or {}
    identity = HostProviderVersion(
        identity_data.get("host", ""),
        identity_data.get("provider", ""),
        identity_data.get("version", ""),
    )
    command_checks = tuple(
        CommandCheck(
            item.get("name", ""),
            item.get("command", ""),
            item.get("passed", False),
            item.get("evidence", ""),
            item.get("exit_code"),
        )
        if isinstance(item, Mapping)
        else CommandCheck("", "", False, "")
        for item in _items(data.get("command_checks"))
    )
    mcp_checks = tuple(
        MCPCheck(
            item.get("name", ""),
            item.get("method", ""),
            item.get("passed", False),
            item.get("evidence", ""),
            item.get("transport", ""),
        )
        if isinstance(item, Mapping)
        else MCPCheck("", "", False, "", "")
        for item in _items(data.get("mcp_checks"))
    )
    fallback_data = _mapping(data.get("fallback")) or {}
    return CompatibilityCertificate(
        schema_version=data.get("schema_version", 0),
        identity=identity,
        command_checks=command_checks,
        mcp_checks=mcp_checks,
        fallback=Fallback(
            fallback_data.get("mode", ""),
            fallback_data.get("command"),
            fallback_data.get("reason"),
        ),
        readiness=data.get("readiness", ""),
        evidence_hash=data.get("evidence_hash", ""),
    )
