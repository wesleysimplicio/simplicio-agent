"""Bounded, additive support-bundle contract for issue #135.

This module records safe operational receipts only.  It does not install,
run doctor, create backups, collect files, read memory databases, or upload a
bundle.  A caller that owns those workflows can provide their already-created
metadata and receive a deterministic, explicitly complete or incomplete
receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any, Final, Mapping


ISSUE_NUMBER: Final[int] = 135
SCHEMA: Final[str] = "simplicio.support-bundle/v1"
MAX_ARTIFACTS: Final[int] = 32
MAX_RECENT_ERRORS: Final[int] = 20
MAX_EVIDENCE_IDS: Final[int] = 50
MAX_REDACT_DEPTH: Final[int] = 5
MAX_REDACT_ITEMS: Final[int] = 64

REDACTED: Final[str] = "[REDACTED]"
EXCLUDED: Final[str] = "[EXCLUDED]"
_OMIT = object()
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?key|client[_-]?secret|secret|token|password|"
    r"passwd|credential|authorization|cookie|private[_-]?key|webhook|"
    r"connection[_-]?string|database[_-]?url|mnemonic|seed|jwt)",
    re.IGNORECASE,
)
_EXCLUDED_KEY_RE = re.compile(
    r"(?:prompt|response|completion|message|file[_-]?content|raw[_-]?content|"
    r"memory(?:[_-]?database)?|sqlite|session[_-]?data|conversation)",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|secret|token|"
    r"password|passwd|authorization|cookie|webhook)\b\s*[:=]\s*"
    r"[^\s,;]+"
)
_SECRET_TOKEN_RE = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"(?:sk|rk|pk|gh[pousr]|github_pat|xox[baprs]|AIza|AKIA)[A-Za-z0-9_.-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{16,}|-----BEGIN [^-]*PRIVATE KEY-----)"
)
_PERSONAL_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/]+users[\\/]+[^\\/\s]+(?:[\\/][^\s\"']*)?|"
    r"/home/[^/\s]+(?:/[^\s\"']*)?|/users/[^/\s]+(?:/[^\s\"']*)?)"
)


class ArtifactKind(StrEnum):
    """Operational artifact categories represented by the receipt."""

    INSTALL = "install"
    DOCTOR = "doctor"
    BACKUP = "backup"
    SUPPORT = "support"


class ArtifactStatus(StrEnum):
    """Evidence state for an artifact, never an execution result."""

    VERIFIED = "verified"
    DECLARED = "declared"
    UNAVAILABLE = "unavailable"


class DoctorStatus(StrEnum):
    """Bounded doctor result supplied by the caller."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_RUN = "not_run"


class BundleStatus(StrEnum):
    """Whether all required receipt categories are present and verified."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _clean_text(value: str) -> str:
    """Redact credential-shaped text before it enters a public receipt."""

    return _Redactor().text(_require_text(value, "text"))


class _Redactor:
    """Small, deterministic, recursive redactor used at the output boundary."""

    def __init__(self) -> None:
        self.count = 0

    def text(self, value: str) -> str:
        text = value
        if _SECRET_TOKEN_RE.search(text):
            self.count += 1
            return REDACTED

        redacted = _SECRET_ASSIGNMENT_RE.sub(
            lambda match: self._replace(match), text
        )
        redacted = _PERSONAL_PATH_RE.sub(self._replace_path, redacted)
        return redacted

    def _replace(self, _match: re.Match[str]) -> str:
        self.count += 1
        return REDACTED

    def _replace_path(self, _match: re.Match[str]) -> str:
        self.count += 1
        return "[REDACTED_PATH]"

    def value(self, value: Any, *, key: str | None = None, depth: int = 0) -> Any:
        if key and _EXCLUDED_KEY_RE.search(key):
            self.count += 1
            return _OMIT
        if key and _SECRET_KEY_RE.search(key):
            self.count += 1
            return REDACTED
        if depth > MAX_REDACT_DEPTH:
            self.count += 1
            return "[OMITTED: depth limit]"
        if value is None or isinstance(value, (bool, int, str)):
            return self.text(value) if isinstance(value, str) else value
        if isinstance(value, float):
            if not math.isfinite(value):
                self.count += 1
                return REDACTED
            return value
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for index, (raw_key, item) in enumerate(value.items()):
                if index >= MAX_REDACT_ITEMS:
                    self.count += 1
                    result["[OMITTED: item limit]"] = EXCLUDED
                    break
                name = self.text(str(raw_key))
                clean_item = self.value(item, key=str(raw_key), depth=depth + 1)
                if clean_item is not _OMIT:
                    result[name] = clean_item
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
            result = [
                clean
                for item in items[:MAX_REDACT_ITEMS]
                if (clean := self.value(item, depth=depth + 1)) is not _OMIT
            ]
            if len(items) > MAX_REDACT_ITEMS:
                self.count += 1
                result.append("[OMITTED: item limit]")
            return result
        self.count += 1
        return "[OMITTED: unsupported value]"


def redact_value(value: Any) -> Any:
    """Return JSON-safe metadata with secrets and sensitive content removed."""

    return _Redactor().value(value)


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Redact a configuration mapping without collecting its source files."""

    if not isinstance(value, Mapping):
        raise TypeError("configuration must be a mapping")
    result = _Redactor().value(value)
    assert isinstance(result, dict)
    return result


def sha256_bytes(value: bytes) -> str:
    """Return a SHA-256 checksum for caller-owned bytes."""

    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    """Return a SHA-256 checksum for caller-owned UTF-8 text."""

    return sha256_bytes(_require_text(value, "value").encode("utf-8"))


def _bounded_texts(values: tuple[str, ...], field_name: str, limit: int) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if len(values) > limit:
        raise ValueError(f"{field_name} cannot contain more than {limit} items")
    return tuple(_clean_text(value) for value in values)


@dataclass(frozen=True, slots=True)
class EnvironmentMetadata:
    """Shareable environment facts; it deliberately has no host paths or IDs."""

    os_name: str
    architecture: str
    python_version: str | None = None
    agent_version: str | None = None
    runtime_version: str | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("os_name", "architecture"):
            object.__setattr__(self, name, _clean_text(getattr(self, name)))
        for name in ("python_version", "agent_version", "runtime_version"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _clean_text(value))
        object.__setattr__(
            self,
            "capabilities",
            _bounded_texts(self.capabilities, "capabilities", MAX_EVIDENCE_IDS),
        )


@dataclass(frozen=True, slots=True)
class SupportArtifact:
    """Metadata for one artifact, without path, content, or archive bytes."""

    kind: ArtifactKind
    name: str
    version: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    status: ArtifactStatus = ArtifactStatus.DECLARED
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ArtifactKind):
            raise TypeError("kind must be an ArtifactKind")
        name = _clean_text(self.name)
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("artifact name must be a logical name, not a path")
        object.__setattr__(self, "name", name)
        if self.version is not None:
            object.__setattr__(self, "version", _clean_text(self.version))
        if self.sha256 is not None:
            checksum = _require_text(self.sha256, "sha256").lower()
            if not _SHA256_RE.fullmatch(checksum):
                raise ValueError("sha256 must be a 64-character hexadecimal digest")
            object.__setattr__(self, "sha256", checksum)
        if self.size_bytes is not None:
            if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
                raise TypeError("size_bytes must be a non-negative integer")
            if self.size_bytes < 0:
                raise ValueError("size_bytes must be a non-negative integer")
        if not isinstance(self.status, ArtifactStatus):
            raise TypeError("status must be an ArtifactStatus")
        object.__setattr__(
            self,
            "evidence_ids",
            _bounded_texts(self.evidence_ids, "evidence_ids", MAX_EVIDENCE_IDS),
        )


ArtifactEvidence = SupportArtifact


@dataclass(frozen=True, slots=True)
class DoctorEvidence:
    """Limited doctor output; raw logs and command output are not accepted."""

    status: DoctorStatus = DoctorStatus.NOT_RUN
    checks: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, DoctorStatus):
            raise TypeError("status must be a DoctorStatus")
        object.__setattr__(self, "checks", _bounded_texts(self.checks, "checks", MAX_EVIDENCE_IDS))
        object.__setattr__(self, "errors", _bounded_texts(self.errors, "errors", MAX_RECENT_ERRORS))
        object.__setattr__(
            self,
            "evidence_ids",
            _bounded_texts(self.evidence_ids, "evidence_ids", MAX_EVIDENCE_IDS),
        )


@dataclass(frozen=True, slots=True)
class SupportBundle:
    """Safe, deterministic bundle receipt produced by the bounded contract."""

    status: BundleStatus
    environment: EnvironmentMetadata | None
    artifacts: tuple[SupportArtifact, ...]
    doctor: DoctorEvidence
    configuration: Mapping[str, Any]
    recent_errors: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    incomplete_reasons: tuple[str, ...] = ()
    redactions_applied: int = 0
    issue_number: int = ISSUE_NUMBER

    @property
    def is_complete(self) -> bool:
        return self.status is BundleStatus.COMPLETE

    @property
    def is_incomplete(self) -> bool:
        return self.status is BundleStatus.INCOMPLETE

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "issue_number": self.issue_number,
            "status": self.status.value,
            "environment": _environment_dict(self.environment),
            "artifacts": [_artifact_dict(item) for item in self.artifacts],
            "doctor": {
                "status": self.doctor.status.value,
                "checks": list(self.doctor.checks),
                "errors": list(self.doctor.errors),
                "evidence_ids": list(self.doctor.evidence_ids),
            },
            "configuration": redact_mapping(self.configuration),
            "recent_errors": list(self.recent_errors),
            "evidence_ids": list(self.evidence_ids),
            "incomplete_reasons": list(self.incomplete_reasons),
            "redactions_applied": self.redactions_applied,
        }

    def to_json(self) -> str:
        """Serialize the receipt deterministically for a caller-owned export."""

        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)


@dataclass(frozen=True, slots=True)
class SupportBundleContract:
    """Input contract for issue #135; it never runs an operational workflow."""

    environment: EnvironmentMetadata | None = None
    artifacts: tuple[SupportArtifact, ...] = ()
    doctor: DoctorEvidence = field(default_factory=DoctorEvidence)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    recent_errors: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    issue_number: int = ISSUE_NUMBER

    def __post_init__(self) -> None:
        if self.issue_number != ISSUE_NUMBER:
            raise ValueError(f"issue_number must be {ISSUE_NUMBER}")
        if not isinstance(self.artifacts, tuple):
            raise TypeError("artifacts must be a tuple")
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise ValueError(f"artifacts cannot contain more than {MAX_ARTIFACTS} items")
        if not all(isinstance(item, SupportArtifact) for item in self.artifacts):
            raise TypeError("artifacts must contain SupportArtifact instances")
        if not isinstance(self.doctor, DoctorEvidence):
            raise TypeError("doctor must be a DoctorEvidence instance")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("configuration must be a mapping")
        object.__setattr__(
            self,
            "recent_errors",
            _bounded_texts(self.recent_errors, "recent_errors", MAX_RECENT_ERRORS),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _bounded_texts(self.evidence_ids, "evidence_ids", MAX_EVIDENCE_IDS),
        )

    def build(self) -> SupportBundle:
        """Create a redacted receipt and evaluate its bounded completeness."""

        redactor = _Redactor()
        configuration = redactor.value(self.configuration)
        assert isinstance(configuration, dict)
        recent_errors = tuple(redactor.text(item) for item in self.recent_errors)
        evidence_ids = tuple(redactor.text(item) for item in self.evidence_ids)
        reasons: list[str] = []

        if self.environment is None:
            reasons.append("environment metadata is missing")
        if self.doctor.status is DoctorStatus.NOT_RUN:
            reasons.append("doctor evidence is missing")
        elif self.doctor.status is DoctorStatus.FAIL:
            reasons.append("doctor reported failure")

        verified_kinds = {
            item.kind
            for item in self.artifacts
            if item.status is ArtifactStatus.VERIFIED and item.sha256 is not None
        }
        for kind in ArtifactKind:
            if kind not in verified_kinds:
                reasons.append(f"verified {kind.value} artifact checksum is missing")

        if not self.doctor.evidence_ids:
            reasons.append("doctor evidence ID is missing")

        return SupportBundle(
            status=BundleStatus.COMPLETE if not reasons else BundleStatus.INCOMPLETE,
            environment=self.environment,
            artifacts=self.artifacts,
            doctor=self.doctor,
            configuration=configuration,
            recent_errors=recent_errors,
            evidence_ids=evidence_ids,
            incomplete_reasons=tuple(reasons),
            redactions_applied=redactor.count,
            issue_number=self.issue_number,
        )


def build_support_bundle(**kwargs: Any) -> SupportBundle:
    """Convenience constructor for callers that do not need to retain a contract."""

    return SupportBundleContract(**kwargs).build()


def _environment_dict(value: EnvironmentMetadata | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "os_name": value.os_name,
        "architecture": value.architecture,
        "python_version": value.python_version,
        "agent_version": value.agent_version,
        "runtime_version": value.runtime_version,
        "capabilities": list(value.capabilities),
    }


def _artifact_dict(value: SupportArtifact) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "name": value.name,
        "version": value.version,
        "sha256": value.sha256,
        "size_bytes": value.size_bytes,
        "status": value.status.value,
        "evidence_ids": list(value.evidence_ids),
    }


__all__ = [
    "ArtifactEvidence",
    "ArtifactKind",
    "ArtifactStatus",
    "BundleStatus",
    "DoctorEvidence",
    "DoctorStatus",
    "EnvironmentMetadata",
    "EXCLUDED",
    "ISSUE_NUMBER",
    "MAX_ARTIFACTS",
    "MAX_EVIDENCE_IDS",
    "MAX_RECENT_ERRORS",
    "REDACTED",
    "SCHEMA",
    "SupportArtifact",
    "SupportBundle",
    "SupportBundleContract",
    "build_support_bundle",
    "redact_mapping",
    "redact_value",
    "sha256_bytes",
    "sha256_text",
]
