"""Bounded metadata gate for physics-inspired imports.

This additive contract checks that an import manifest declares its hypothesis,
assumptions, falsifier, boundary, licensing, pinned provenance, and
reproducible benchmark evidence.  It does not validate physics, ASOLARIA, a
formula, or the truth of any scientific claim.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


CONTRACT_SCHEMA = "physics-import/v1"
MAX_TEXT_LENGTH = 8_192
MAX_COLLECTION_ITEMS = 128
MAX_ERRORS = 64
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")
INTEGRITY_SCOPE = (
    "manifest completeness and reproducibility metadata only; no ASOLARIA, "
    "physics, formula, or scientific-truth validation"
)


class ScientificIntegrityError(ValueError):
    """Raised when a scientific-import manifest fails this bounded gate."""


@dataclass(frozen=True, slots=True)
class IntegrityGateResult:
    """Deterministic result of evaluating one import manifest."""

    accepted: bool
    errors: tuple[str, ...]
    scope: str = INTEGRITY_SCOPE

    @property
    def valid(self) -> bool:
        """Return whether the manifest passed every metadata check."""

        return self.accepted

    def require_valid(self) -> None:
        """Raise a stable error instead of allowing an invalid manifest through."""

        if not self.accepted:
            raise ScientificIntegrityError("scientific integrity gate failed: " + "; ".join(self.errors))


def _has_text(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str):
        errors.append(f"{path} must be a non-empty string")
        return False
    if not value.strip():
        errors.append(f"{path} must be a non-empty string")
        return False
    if len(value) > MAX_TEXT_LENGTH:
        errors.append(f"{path} exceeds {MAX_TEXT_LENGTH} characters")
        return False
    return True


def _has_content(value: Any, path: str, errors: list[str]) -> bool:
    if isinstance(value, str):
        return _has_text(value, path, errors)
    if isinstance(value, Mapping):
        if not value:
            errors.append(f"{path} must not be empty")
            return False
        if len(value) > MAX_COLLECTION_ITEMS:
            errors.append(f"{path} exceeds {MAX_COLLECTION_ITEMS} entries")
            return False
        return True
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if not value:
            errors.append(f"{path} must not be empty")
            return False
        if len(value) > MAX_COLLECTION_ITEMS:
            errors.append(f"{path} exceeds {MAX_COLLECTION_ITEMS} entries")
            return False
        for index, item in enumerate(value):
            _has_text(item, f"{path}[{index}]", errors)
        return True
    errors.append(f"{path} must contain text or a non-empty collection")
    return False


def _required_text(manifest: Mapping[str, Any], name: str, errors: list[str]) -> None:
    if name not in manifest:
        errors.append(f"missing required field: {name}")
        return
    _has_content(manifest[name], name, errors)


def _validate_source(manifest: Mapping[str, Any], errors: list[str]) -> None:
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        errors.append("source must be a mapping with url and commit")
        return
    if "url" not in source:
        errors.append("missing required field: source.url")
    else:
        _has_text(source["url"], "source.url", errors)
    if "commit" not in source:
        errors.append("missing required field: source.commit")
    elif not _has_text(source["commit"], "source.commit", errors):
        pass
    elif not COMMIT_PATTERN.fullmatch(source["commit"].strip()):
        errors.append("source.commit must be an immutable git commit SHA")


def _validate_benchmark(manifest: Mapping[str, Any], errors: list[str]) -> None:
    evidence = manifest.get("benchmark_evidence")
    if not isinstance(evidence, Mapping):
        errors.append(
            "benchmark_evidence must be a mapping with command, dataset, result, and reproducible"
        )
        return
    for name in ("command", "dataset", "result"):
        if name not in evidence:
            errors.append(f"missing required field: benchmark_evidence.{name}")
        else:
            _has_content(evidence[name], f"benchmark_evidence.{name}", errors)
    if evidence.get("reproducible") is not True:
        errors.append("benchmark_evidence.reproducible must be true")


def validate_manifest(manifest: Any) -> IntegrityGateResult:
    """Evaluate a ``physics-import/v1`` manifest without performing network I/O.

    Unknown fields are intentionally tolerated so callers can add domain
    metadata without widening this gate.  Missing or malformed required data
    always produces ``accepted=False``.
    """

    if not isinstance(manifest, Mapping):
        return IntegrityGateResult(False, ("manifest must be a mapping",))

    errors: list[str] = []
    if manifest.get("schema") != CONTRACT_SCHEMA:
        if "schema" not in manifest:
            errors.append("missing required field: schema")
        else:
            errors.append(f"schema must equal {CONTRACT_SCHEMA!r}")

    for name in ("hypothesis", "assumptions", "falsifier", "boundary", "license"):
        _required_text(manifest, name, errors)
    _validate_source(manifest, errors)
    _validate_benchmark(manifest, errors)

    if len(errors) > MAX_ERRORS:
        errors = errors[:MAX_ERRORS] + ["validation error limit exceeded"]
    return IntegrityGateResult(not errors, tuple(errors))


def assert_valid_manifest(manifest: Any) -> IntegrityGateResult:
    """Validate and return the result, raising on any missing required data."""

    result = validate_manifest(manifest)
    result.require_valid()
    return result


def check_manifest(manifest: Any) -> bool:
    """Return only the fail-closed acceptance bit for simple callers."""

    return validate_manifest(manifest).accepted


__all__ = [
    "CONTRACT_SCHEMA",
    "INTEGRITY_SCOPE",
    "IntegrityGateResult",
    "ScientificIntegrityError",
    "assert_valid_manifest",
    "check_manifest",
    "validate_manifest",
]
