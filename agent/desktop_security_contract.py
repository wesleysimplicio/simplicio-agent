"""Bounded, additive Desktop security/privacy policy contract.

This module is a pure policy model for issue #134.  It does not store or
retrieve secrets, grant OS permissions, emit telemetry, delete data, or claim
full Desktop hardening.  Callers must use the returned decision before doing
any side effect; an unsafe policy or incomplete approval is denied.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping


DESKTOP_SECURITY_CONTRACT_SCHEMA = "simplicio.desktop-security-contract"
DESKTOP_SECURITY_CONTRACT_VERSION = "simplicio.desktop-security-contract/v1"
MAX_RETENTION_SECONDS = 30 * 24 * 60 * 60


class SecretBackend(StrEnum):
    """Backends represented by the contract; none of them are implemented here."""

    NATIVE_VAULT = "native_vault"
    CONSENTED_FALLBACK = "consented_fallback"


class Permission(StrEnum):
    """Capabilities that a Desktop action must request explicitly."""

    READ_WORKSPACE = "read_workspace"
    WRITE_WORKSPACE = "write_workspace"
    TERMINAL = "terminal"
    BROWSER = "browser"
    COMPUTER_USE = "computer_use"
    NETWORK = "network"
    CREDENTIALS = "credentials"


class TelemetryMode(StrEnum):
    """External telemetry is opt-in, never an implicit default."""

    OFF = "off"
    OPT_IN = "opt_in"


class RiskLevel(StrEnum):
    """Ordered action risk levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class ViolationCode(StrEnum):
    """Stable reasons for a fail-closed decision."""

    UNSAFE_SECRET_POLICY = "unsafe_secret_policy"
    SECRET_REFERENCE_REQUIRED = "secret_reference_required"
    PERMISSION_NOT_GRANTED = "permission_not_granted"
    TELEMETRY_NOT_OPTED_IN = "telemetry_not_opted_in"
    RETENTION_UNBOUNDED = "retention_unbounded"
    REDACTION_DISABLED = "redaction_disabled"
    RISK_APPROVAL_REQUIRED = "risk_approval_required"
    INVALID_APPROVAL = "invalid_approval"
    INVALID_SETTING = "invalid_setting"


@dataclass(frozen=True, slots=True)
class SecurityViolation:
    """Machine-readable, non-secret explanation of a denied operation."""

    code: ViolationCode
    detail: str


@dataclass(frozen=True, slots=True)
class SecretReference:
    """A handle to a secret; raw material is deliberately absent."""

    name: str
    backend: SecretBackend = SecretBackend.NATIVE_VAULT

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("secret reference name must be non-empty")
        if not isinstance(self.backend, SecretBackend):
            raise TypeError("secret reference backend must be a SecretBackend")

    def to_dict(self) -> dict[str, str]:
        """Serialize only the handle, never secret material."""

        return {"name": self.name, "backend": self.backend.value}


@dataclass(frozen=True, slots=True)
class SecretHandlingPolicy:
    """Rules for representing credentials without accepting raw values."""

    backend: SecretBackend = SecretBackend.NATIVE_VAULT
    fallback_consent: bool = False
    allow_plaintext: bool = False
    allow_process_arguments: bool = False
    expose_to_ui: bool = False

    def violations(self) -> tuple[SecurityViolation, ...]:
        issues: list[SecurityViolation] = []
        if not isinstance(self.backend, SecretBackend):
            issues.append(SecurityViolation(ViolationCode.INVALID_SETTING, "unknown secret backend"))
        elif self.backend is SecretBackend.CONSENTED_FALLBACK and not self.fallback_consent:
            issues.append(
                SecurityViolation(
                    ViolationCode.UNSAFE_SECRET_POLICY,
                    "fallback secret storage requires explicit consent",
                )
            )
        if self.allow_plaintext:
            issues.append(
                SecurityViolation(
                    ViolationCode.UNSAFE_SECRET_POLICY,
                    "plaintext secret storage is never allowed",
                )
            )
        if self.allow_process_arguments:
            issues.append(
                SecurityViolation(
                    ViolationCode.UNSAFE_SECRET_POLICY,
                    "secrets must not be placed in process arguments",
                )
            )
        if self.expose_to_ui:
            issues.append(
                SecurityViolation(
                    ViolationCode.UNSAFE_SECRET_POLICY,
                    "secret material must not be exposed in the UI",
                )
            )
        return tuple(issues)


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """Allowlist of Desktop capabilities; an empty default denies all."""

    granted: frozenset[Permission] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "granted", frozenset(self.granted))

    def allows(self, permission: Permission) -> bool:
        return isinstance(permission, Permission) and permission in self.granted

    def violations(self) -> tuple[SecurityViolation, ...]:
        if all(isinstance(item, Permission) for item in self.granted):
            return ()
        return (
            SecurityViolation(ViolationCode.INVALID_SETTING, "permission policy contains an unknown capability"),
        )


_SAFE_TELEMETRY_FIELDS = frozenset(
    {"event", "status", "duration_ms", "version", "error_code"}
)


@dataclass(frozen=True, slots=True)
class TelemetryPolicy:
    """Default-off external telemetry with a small metadata-only allowlist."""

    mode: TelemetryMode = TelemetryMode.OFF
    consent: bool = False
    destination: str | None = None
    fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", frozenset(self.fields))

    @property
    def external_enabled(self) -> bool:
        return (
            self.mode is TelemetryMode.OPT_IN
            and self.consent
            and isinstance(self.destination, str)
            and bool(self.destination.strip())
        )

    def violations(self) -> tuple[SecurityViolation, ...]:
        issues: list[SecurityViolation] = []
        if not isinstance(self.mode, TelemetryMode):
            issues.append(SecurityViolation(ViolationCode.INVALID_SETTING, "unknown telemetry mode"))
            return tuple(issues)
        if self.mode is TelemetryMode.OPT_IN and not self.consent:
            issues.append(
                SecurityViolation(
                    ViolationCode.TELEMETRY_NOT_OPTED_IN,
                    "external telemetry requires explicit consent",
                )
            )
        if self.mode is TelemetryMode.OPT_IN and (
            not isinstance(self.destination, str) or not self.destination.strip()
        ):
            issues.append(
                SecurityViolation(
                    ViolationCode.INVALID_SETTING,
                    "opt-in telemetry requires a declared destination",
                )
            )
        if not self.fields.issubset(_SAFE_TELEMETRY_FIELDS):
            issues.append(
                SecurityViolation(
                    ViolationCode.UNSAFE_SECRET_POLICY,
                    "telemetry fields must be metadata-only and allowlisted",
                )
            )
        return tuple(issues)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Finite retention with deletion required at expiry."""

    max_age_seconds: int | None = 24 * 60 * 60
    max_records: int | None = 1_000
    delete_on_expiry: bool = True

    def violations(self) -> tuple[SecurityViolation, ...]:
        issues: list[SecurityViolation] = []
        if (
            self.max_age_seconds is None
            or isinstance(self.max_age_seconds, bool)
            or not isinstance(self.max_age_seconds, int)
            or self.max_age_seconds < 0
            or self.max_age_seconds > MAX_RETENTION_SECONDS
        ):
            issues.append(
                SecurityViolation(
                    ViolationCode.RETENTION_UNBOUNDED,
                    f"max_age_seconds must be between 0 and {MAX_RETENTION_SECONDS}",
                )
            )
        if (
            self.max_records is None
            or isinstance(self.max_records, bool)
            or not isinstance(self.max_records, int)
            or self.max_records <= 0
        ):
            issues.append(
                SecurityViolation(
                    ViolationCode.RETENTION_UNBOUNDED,
                    "max_records must be a positive finite integer",
                )
            )
        if not self.delete_on_expiry:
            issues.append(
                SecurityViolation(
                    ViolationCode.RETENTION_UNBOUNDED,
                    "retained data must be deleted at expiry",
                )
            )
        return tuple(issues)


_DEFAULT_SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|credential|password|secret|token)\b\s*[=:]\s*)([^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Central deterministic redaction for structured and textual evidence."""

    enabled: bool = True
    replacement: str = "[REDACTED]"
    sensitive_fields: frozenset[str] = _DEFAULT_SENSITIVE_FIELDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sensitive_fields",
            frozenset(field.lower() for field in self.sensitive_fields),
        )

    def violations(self) -> tuple[SecurityViolation, ...]:
        if not self.enabled:
            return (
                SecurityViolation(
                    ViolationCode.REDACTION_DISABLED,
                    "redaction must remain enabled for Desktop evidence",
                ),
            )
        if not isinstance(self.replacement, str) or not self.replacement:
            return (
                SecurityViolation(ViolationCode.INVALID_SETTING, "redaction replacement must be non-empty"),
            )
        if not self.sensitive_fields:
            return (
                SecurityViolation(ViolationCode.INVALID_SETTING, "at least one sensitive field is required"),
            )
        return ()

    def redact(self, value: Any) -> Any:
        """Return a redacted copy; an unsafe redactor masks the whole value."""

        if self.violations():
            return self.replacement if self.replacement else "[REDACTED_UNSAFE_POLICY]"
        if isinstance(value, Mapping):
            return {
                key: self.replacement
                if isinstance(key, str) and key.lower() in self.sensitive_fields
                else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, str):
            return _SECRET_ASSIGNMENT_RE.sub(rf"\1{self.replacement}", value)
        return value


@dataclass(frozen=True, slots=True)
class RiskApproval:
    """Short-lived, scoped human approval for high-risk actions."""

    approved: bool
    approver: str | None
    reason: str | None
    scope: str | None
    expires_at: float | None
    approval_id: str | None = None

    def is_valid(self, *, required_scope: str, now: float) -> bool:
        return (
            self.approved
            and isinstance(self.approver, str)
            and bool(self.approver.strip())
            and isinstance(self.reason, str)
            and bool(self.reason.strip())
            and self.scope == required_scope
            and isinstance(self.expires_at, (int, float))
            and not isinstance(self.expires_at, bool)
            and isfinite(self.expires_at)
            and self.expires_at > now
        )


@dataclass(frozen=True, slots=True)
class DesktopActionRequest:
    """Requested side-effect metadata; the contract never performs it."""

    action: str
    scope: str
    permissions: frozenset[Permission] = frozenset()
    risk: RiskLevel = RiskLevel.LOW
    secret_required: bool = False
    secret_reference: SecretReference | None = None
    telemetry_requested: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("action must be non-empty")
        if not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError("scope must be non-empty")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Result of policy evaluation, safe to log because it contains no values."""

    allowed: bool
    violations: tuple[SecurityViolation, ...] = ()


@dataclass(frozen=True, slots=True)
class DesktopSecurityContract:
    """Composition of bounded privacy/security controls for a Desktop caller."""

    secret_handling: SecretHandlingPolicy = field(default_factory=SecretHandlingPolicy)
    permissions: PermissionPolicy = field(default_factory=PermissionPolicy)
    telemetry: TelemetryPolicy = field(default_factory=TelemetryPolicy)
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    redaction: RedactionPolicy = field(default_factory=RedactionPolicy)
    approval_required_at: RiskLevel = RiskLevel.HIGH

    @property
    def schema(self) -> str:
        return DESKTOP_SECURITY_CONTRACT_SCHEMA

    @property
    def schema_version(self) -> str:
        return DESKTOP_SECURITY_CONTRACT_VERSION

    def violations(self) -> tuple[SecurityViolation, ...]:
        issues: list[SecurityViolation] = []
        if not isinstance(self.approval_required_at, RiskLevel):
            issues.append(SecurityViolation(ViolationCode.INVALID_SETTING, "unknown approval threshold"))
        for policy in (
            self.secret_handling,
            self.permissions,
            self.telemetry,
            self.retention,
            self.redaction,
        ):
            issues.extend(policy.violations())
        return tuple(issues)

    @property
    def is_safe(self) -> bool:
        return not self.violations()

    def authorize(
        self,
        request: DesktopActionRequest,
        *,
        approval: RiskApproval | None = None,
        now: float | None = None,
    ) -> AuthorizationDecision:
        """Authorize metadata only; every unsafe condition denies the action."""

        issues = list(self.violations())
        timestamp = time.time() if now is None else now
        if not isinstance(request, DesktopActionRequest):
            return AuthorizationDecision(
                False,
                (SecurityViolation(ViolationCode.INVALID_SETTING, "invalid action request"),),
            )
        if not isinstance(request.risk, RiskLevel):
            issues.append(SecurityViolation(ViolationCode.INVALID_SETTING, "unknown action risk"))
        if any(not isinstance(item, Permission) for item in request.permissions):
            issues.append(SecurityViolation(ViolationCode.INVALID_SETTING, "unknown requested permission"))
        else:
            for permission in request.permissions:
                if not self.permissions.allows(permission):
                    issues.append(
                        SecurityViolation(
                            ViolationCode.PERMISSION_NOT_GRANTED,
                            f"permission {permission.value!r} is not granted",
                        )
                    )
        if request.secret_required:
            if not isinstance(request.secret_reference, SecretReference):
                issues.append(
                    SecurityViolation(
                        ViolationCode.SECRET_REFERENCE_REQUIRED,
                        "secret actions require a vault reference, never raw material",
                    )
                )
            elif request.secret_reference.backend is not self.secret_handling.backend:
                issues.append(
                    SecurityViolation(
                        ViolationCode.UNSAFE_SECRET_POLICY,
                        "secret reference backend does not match policy",
                    )
                )
        if request.telemetry_requested and not self.telemetry.external_enabled:
            issues.append(
                SecurityViolation(
                    ViolationCode.TELEMETRY_NOT_OPTED_IN,
                    "telemetry request is not explicitly enabled and consented",
                )
            )
        if (
            isinstance(request.risk, RiskLevel)
            and isinstance(self.approval_required_at, RiskLevel)
            and _RISK_ORDER[request.risk] >= _RISK_ORDER[self.approval_required_at]
        ):
            if approval is None:
                issues.append(
                    SecurityViolation(
                        ViolationCode.RISK_APPROVAL_REQUIRED,
                        "high-risk actions require a scoped approval",
                    )
                )
            elif not approval.is_valid(required_scope=request.scope, now=timestamp):
                issues.append(
                    SecurityViolation(
                        ViolationCode.INVALID_APPROVAL,
                        "approval is missing, expired, or outside the requested scope",
                    )
                )
        return AuthorizationDecision(not issues, tuple(issues))

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy metadata without secret material or runtime state."""

        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "secret_handling": {
                "backend": self.secret_handling.backend.value
                if isinstance(self.secret_handling.backend, SecretBackend)
                else None,
                "fallback_consent": self.secret_handling.fallback_consent,
                "allow_plaintext": self.secret_handling.allow_plaintext,
                "allow_process_arguments": self.secret_handling.allow_process_arguments,
                "expose_to_ui": self.secret_handling.expose_to_ui,
            },
            "permissions": sorted(
                permission.value
                for permission in self.permissions.granted
                if isinstance(permission, Permission)
            ),
            "telemetry": {
                "mode": self.telemetry.mode.value
                if isinstance(self.telemetry.mode, TelemetryMode)
                else None,
                "consent": self.telemetry.consent,
                "destination": self.telemetry.destination,
                "fields": sorted(self.telemetry.fields),
            },
            "retention": {
                "max_age_seconds": self.retention.max_age_seconds,
                "max_records": self.retention.max_records,
                "delete_on_expiry": self.retention.delete_on_expiry,
            },
            "redaction": {
                "enabled": self.redaction.enabled,
                "replacement": self.redaction.replacement,
                "sensitive_fields": sorted(self.redaction.sensitive_fields),
            },
            "approval_required_at": self.approval_required_at.value
            if isinstance(self.approval_required_at, RiskLevel)
            else None,
        }


__all__ = [
    "DESKTOP_SECURITY_CONTRACT_SCHEMA",
    "DESKTOP_SECURITY_CONTRACT_VERSION",
    "MAX_RETENTION_SECONDS",
    "SecretBackend",
    "SecretReference",
    "SecretHandlingPolicy",
    "Permission",
    "PermissionPolicy",
    "TelemetryMode",
    "TelemetryPolicy",
    "RetentionPolicy",
    "RedactionPolicy",
    "RiskLevel",
    "RiskApproval",
    "DesktopActionRequest",
    "ViolationCode",
    "SecurityViolation",
    "AuthorizationDecision",
    "DesktopSecurityContract",
]
