"""Fail-closed validation for pinned Simplicio Runtime lock manifests.

This module validates release metadata without downloading or executing an
artifact.  It intentionally reports signature verification separately: a
structurally valid lock with an unproven signature is not stable-ready.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

LOCK_SCHEMA = "runtime-lock/v2"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def target_key(system: str | None = None, machine: str | None = None) -> str:
    """Return the normalized ``os-arch`` key used by lock assets."""

    os_name = (system or platform.system()).lower()
    arch = (machine or platform.machine()).lower()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    return f"{os_name}-{arch}"


@dataclass(frozen=True)
class RuntimeLockReceipt:
    """JSON-ready result of validating one lock manifest and target."""

    schema: str
    target: str
    valid: bool
    stable_ready: bool
    signature_status: str
    asset: Mapping[str, Any] | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target": self.target,
            "valid": self.valid,
            "stable_ready": self.stable_ready,
            "signature_status": self.signature_status,
            "asset": dict(self.asset) if self.asset is not None else None,
            "errors": list(self.errors),
        }


def _semver(value: object) -> bool:
    return isinstance(value, str) and _SEMVER.fullmatch(value) is not None


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_lock(
    payload: Mapping[str, Any],
    *,
    target: str,
    artifact: str | Path | None = None,
) -> RuntimeLockReceipt:
    """Validate lock metadata and optionally verify a local artifact's bytes."""

    errors: list[str] = []
    if payload.get("schema") != LOCK_SCHEMA:
        errors.append(f"schema must be {LOCK_SCHEMA}")
    minimum = payload.get("min_version")
    if not _semver(minimum):
        errors.append("min_version must be strict semver")

    assets = payload.get("assets")
    selected = assets.get(target) if isinstance(assets, Mapping) else None
    if not isinstance(selected, Mapping):
        errors.append(f"no asset for target {target}")
        return RuntimeLockReceipt(
            str(payload.get("schema", "")),
            target,
            False,
            False,
            "unknown",
            None,
            tuple(errors),
        )

    required = ("name", "version", "url", "sha256", "size", "target")
    for field in required:
        if selected.get(field) is None:
            errors.append(f"asset.{field} must be non-null")
    if not isinstance(selected.get("name"), str) or not selected.get("name"):
        errors.append("asset.name must be non-empty")
    if not _semver(selected.get("version")):
        errors.append("asset.version must be strict semver")
    url = selected.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        errors.append("asset.url must be an immutable HTTPS URL")
    digest = selected.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append("asset.sha256 must be a 64-character hex digest")
    size = selected.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        errors.append("asset.size must be a positive integer")

    metadata = selected.get("target")
    if (
        not isinstance(metadata, Mapping)
        or target_key(metadata.get("os"), metadata.get("arch")) != target
    ):
        errors.append("asset.target does not match requested target")

    if artifact is not None and not errors:
        artifact_path = Path(artifact)
        if not artifact_path.is_file():
            errors.append("artifact file is missing")
        else:
            if artifact_path.stat().st_size != size:
                errors.append("artifact size does not match lock")
            if _digest(artifact_path).lower() != str(digest).lower():
                errors.append("artifact sha256 does not match lock")

    signature_status = str(
        payload.get("provenance", {}).get("signature_status", "unverified")
    )
    valid = not errors
    stable_ready = valid and signature_status == "verified"
    return RuntimeLockReceipt(
        str(payload.get("schema", "")),
        target,
        valid,
        stable_ready,
        signature_status,
        selected,
        tuple(errors),
    )


def load_lock(path: str | Path) -> dict[str, Any]:
    """Load a JSON lock file without applying permissive defaults."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime lock must be a JSON object")
    return value


__all__ = [
    "LOCK_SCHEMA",
    "RuntimeLockReceipt",
    "load_lock",
    "target_key",
    "validate_lock",
]
