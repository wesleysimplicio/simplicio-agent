"""Managed simplicio-runtime dependency (ADR-0003).

The agent and the runtime kernel live in **separate repositories**, but the
agent treats the kernel binary as a *managed, pinned dependency* rather than
an optional PATH discovery. ``runtime.lock`` at the repo root pins the
minimum kernel version; this module owns the handshake, resolution order,
and install/update path into ``~/.simplicio/bin``.

Routing doctrine (AGENTS.md "Tool routing") is unchanged: Hermes-native
tools stay first for reading/searching/reasoning; the simplicio kernel is
the actuator for execution, deterministic edits, validation, and evidence.
This module only guarantees the actuator is *present and current* — it
never widens what the kernel is asked to do.

Resolution order (first hit wins):

1. ``HERMES_KERNEL_BIN`` env override (tests / development).
2. Bare ``simplicio`` on PATH (user-managed installs keep working).
3. The managed install dir ``~/.simplicio/bin`` (what ``ensure_runtime``
   populates).

Install strategies, in order:

* ``gh release download`` of the platform asset from the release repo.
* the immutable HTTPS URL pinned in ``runtime.lock`` (used for tracked
  binaries published from a version tag while release assets are promoted).
* ``cargo build --release`` from the sibling ``simplicio-runtime`` checkout
  (the only path on Windows, which has no published binary asset).

Everything degrades honestly: no strategy available -> a status object that
says exactly what is missing and how to fix it. Nothing here raises into a
conversation turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from tools.runtime_lock_contract import validate_lock_manifest

from tools.runtime_handshake import (
    HANDSHAKE_REASON_HANDSHAKE_FAILED,
    HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME,
    HANDSHAKE_REASON_READY,
    HANDSHAKE_REASON_RUNTIME_MISSING,
    RuntimeHandshake,
    build_runtime_handshake,
)

logger = logging.getLogger(__name__)

_LOCK_FILENAME = "runtime.lock"
_LOCK_SCHEMA = "runtime-lock/v2"
_KERNEL_BIN_ENV = "HERMES_KERNEL_BIN"
_MANAGED_DIR_ENV = "SIMPLICIO_HOME"
_DEV_BUILD_ENV = "HERMES_RUNTIME_DEV_BUILD"

_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

# Identity handshake (adversarial review #4): a bare X.Y.Z found *anywhere*
# in the output is not enough -- PATH collisions and homonym binaries (e.g.
# an unrelated "Simplicio Agent v0.17.0" banner) must never be mistaken for
# the kernel. Anchored at the start of stdout only (never stderr, which can
# carry unrelated warnings); allows leading whitespace and an optional
# "[- ]runtime" / "v" decoration (matches "simplicio vX.Y.Z",
# "simplicio-runtime vX.Y.Z" and the real "Simplicio Runtime X.Y.Z" banner).
_KERNEL_BANNER_RE = re.compile(
    r"^\s*simplicio(?:[- ]runtime)?\s+v?(\d+)\.(\d+)\.(\d+)",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class RuntimeLockValidation:
    """The bounded, read-only result of validating a runtime lock."""

    valid: bool
    target: str
    asset: Optional[dict]
    errors: tuple[str, ...] = ()
    stable_ready: bool = False
    signature_status: str = "unverified"

    @property
    def detail(self) -> str:
        return "; ".join(self.errors)


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """The simplicio-agent repo root (parent of ``tools/``)."""
    return Path(__file__).resolve().parent.parent


def runtime_lock_path() -> Path:
    """Locate the lock in source and installed data-file layouts.

    Wheels install ``[tool.setuptools.data-files] runtime`` below the active
    Python prefix, while source checkouts keep the lock at repository root.
    Source wins so development and packaged runs use the same contract.
    """
    candidates = (
        repo_root() / _LOCK_FILENAME,
        Path(sys.prefix) / "runtime" / _LOCK_FILENAME,
        Path(sys.executable).resolve().parent / "runtime" / _LOCK_FILENAME,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def load_runtime_lock() -> dict:
    """Read ``runtime.lock`` without manufacturing a pin.

    Missing or unreadable lock data returns an empty object.  The caller then
    runs the normal lock validator, which reports an invalid lock and blocks
    runtime resolution/install.  Applying defaults here would silently turn
    an unpinned installation into a usable one.
    """
    lock_path = runtime_lock_path()
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("runtime.lock must contain a JSON object: %s", lock_path)
            return {}
        return raw
    except FileNotFoundError:
        logger.warning("runtime.lock not found at %s -- refusing unpinned runtime", lock_path)
    except (OSError, ValueError) as exc:
        logger.warning("runtime.lock unreadable (%s) -- refusing unpinned runtime", exc)
    return {}


def _normalize_machine(machine: str) -> str:
    return {"amd64": "x86_64", "aarch64": "arm64"}.get(machine.lower(), machine.lower())


def _target_key(system: Optional[str] = None, machine: Optional[str] = None) -> str:
    system = (system or platform.system()).lower()
    machine = _normalize_machine(machine or platform.machine())
    return f"{system}-{machine}"


def validate_runtime_lock(
    lock: object, *, target: Optional[str] = None
) -> RuntimeLockValidation:
    """Validate the release metadata needed before runtime readiness.

    This is intentionally stricter than JSON parsing. Every asset must carry
    an immutable HTTPS URL, non-null size and SHA-256, a semver release
    version compatible with ``min_version``, and explicit OS/architecture
    metadata matching its map key. A missing current target is unavailable;
    it is never silently replaced with a different target or a sibling build.
    """
    requested = target or _target_key()
    result = validate_lock_manifest(lock, target=requested)
    asset = dict(result.asset) if result.asset is not None else None
    # Keep the manager's established diagnostic vocabulary while the shared
    # receipt contract uses shorter, public-facing messages.
    errors = tuple(
        error.replace(
            "asset.target does not match requested target",
            "asset.target does not match its target key",
        ).replace(
            "no asset for target ",
            "no verified runtime asset for target ",
        )
        for error in result.errors
    )
    return RuntimeLockValidation(
        result.valid,
        result.target,
        asset,
        errors,
        result.stable_ready,
        result.signature_status,
    )

    errors: list[str] = []
    if not isinstance(lock, dict):
        return RuntimeLockValidation(False, requested, None, ("lock is not an object",))

    if lock.get("schema") != _LOCK_SCHEMA:
        errors.append(f"schema must be {_LOCK_SCHEMA}")
    kernel = lock.get("kernel")
    if not isinstance(kernel, str) or not kernel.strip():
        errors.append("kernel must be a non-empty string")
    minimum = lock.get("min_version")
    if not isinstance(minimum, str) or not _STRICT_SEMVER_RE.fullmatch(minimum):
        errors.append("min_version must be a strict semver")

    assets = lock.get("assets")
    if not isinstance(assets, dict) or not assets:
        errors.append("assets must contain at least one target")
        return RuntimeLockValidation(False, requested, None, tuple(errors))

    selected: Optional[dict] = None
    for key, entry in assets.items():
        prefix = f"assets[{key!r}]"
        if not isinstance(key, str) or "-" not in key:
            errors.append(f"{prefix} target key must be <os>-<arch>")
            continue
        key_os, key_arch = key.split("-", 1)
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("name", "version", "url", "sha256", "size", "target"):
            if field not in entry or entry[field] is None:
                errors.append(f"{prefix}.{field} must be non-null")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}.name must be a non-empty string")
        version = entry.get("version")
        if not isinstance(version, str) or not _STRICT_SEMVER_RE.fullmatch(version):
            errors.append(f"{prefix}.version must be a strict semver")
        elif isinstance(minimum, str) and _STRICT_SEMVER_RE.fullmatch(minimum):
            if parse_semver(version) < parse_semver(minimum):
                errors.append(
                    f"{prefix}.version {version} is below min_version {minimum}"
                )
        url = entry.get("url")
        parsed_url = urlparse(url) if isinstance(url, str) else None
        if (
            parsed_url is None
            or parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
            or not isinstance(name, str)
            or not parsed_url.path.rstrip("/").endswith(f"/{name}")
        ):
            errors.append(f"{prefix}.url must be an immutable HTTPS asset URL")
        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            errors.append(f"{prefix}.sha256 must be a 64-character hex digest")
        size = entry.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            errors.append(f"{prefix}.size must be a positive integer")
        target_meta = entry.get("target")
        if not isinstance(target_meta, dict):
            errors.append(f"{prefix}.target must be an object")
        else:
            target_os = target_meta.get("os")
            target_arch = target_meta.get("arch")
            if not isinstance(target_os, str) or not isinstance(target_arch, str):
                errors.append(f"{prefix}.target requires os and arch")
            elif target_os.lower() != key_os.lower() or _normalize_machine(
                target_arch
            ) != _normalize_machine(key_arch):
                errors.append(f"{prefix}.target does not match its target key")
        if key == requested:
            selected = entry

    if selected is None:
        errors.append(f"no verified runtime asset for target {requested}")
    return RuntimeLockValidation(not errors, requested, selected, tuple(errors))


# ---------------------------------------------------------------------------
# Version handshake
# ---------------------------------------------------------------------------


def parse_semver(text: str) -> Optional[tuple[int, int, int]]:
    """Extract the first ``X.Y.Z`` triple from arbitrary version output."""
    m = _SEMVER_RE.search(text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def version_satisfies(installed: str, minimum: str) -> bool:
    """True when ``installed`` >= ``minimum`` (semver triple compare)."""
    inst = parse_semver(installed)
    mini = parse_semver(minimum)
    if mini is None:
        return True
    if inst is None:
        return False
    return inst >= mini


def kernel_version(bin_path: str) -> Optional[str]:
    """Run the kernel version handshake and return its semver, or None.

    Validates *identity*, not just presence of a version-shaped substring:
    ``stdout`` must start with a ``simplicio``/``simplicio-runtime`` banner
    (see ``_KERNEL_BANNER_RE``). A binary that merely shares the name but
    prints an unrelated banner (or puts its version only in stderr) does not
    satisfy the handshake and returns ``None``. Older distributed kernels
    expose ``version`` while newer builds expose ``--version``; both are
    accepted across the release transition.
    """
    try:
        from hermes_cli._subprocess_compat import IS_WINDOWS, windows_hide_flags

        extra = {"creationflags": windows_hide_flags()} if IS_WINDOWS else {}
    except Exception:
        extra = {}
    for command in ("--version", "version"):
        try:
            proc = subprocess.run(
                [bin_path, command],
                capture_output=True,
                text=True,
                timeout=10,
                **extra,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("kernel %s failed for %s: %s", command, bin_path, exc)
            continue
        if proc.returncode != 0:
            continue
        m = _KERNEL_BANNER_RE.match(proc.stdout or "")
        if m:
            return f"{int(m.group(1))}.{int(m.group(2))}.{int(m.group(3))}"
    return None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def managed_bin_dir() -> Path:
    """``~/.simplicio/bin`` (honors ``SIMPLICIO_HOME`` for tests/relocation)."""
    override = os.environ.get(_MANAGED_DIR_ENV, "").strip()
    home = Path(override).expanduser() if override else Path.home() / ".simplicio"
    return home / "bin"


def _bin_name(kernel: str) -> str:
    return f"{kernel}.exe" if sys.platform == "win32" else kernel


def resolve_kernel(lock: Optional[dict] = None) -> tuple[Optional[str], str]:
    """Resolve the kernel binary. Returns ``(path, source)``.

    ``source`` is one of ``env`` | ``path`` | ``managed`` | ``absent`` so
    callers (doctor, telemetry) can say *where* the kernel came from.
    """
    lock = lock or load_runtime_lock()
    kernel = str(lock.get("kernel") or "simplicio")

    override = os.environ.get(_KERNEL_BIN_ENV, "").strip()
    if override:
        resolved = shutil.which(override)
        return (resolved, "env") if resolved else (None, "absent")

    resolved = shutil.which(kernel)
    if resolved:
        return resolved, "path"

    managed = managed_bin_dir() / _bin_name(kernel)
    if managed.is_file() and os.access(managed, os.X_OK):
        return str(managed), "managed"

    return None, "absent"


# ---------------------------------------------------------------------------
# Canonical PATH shim (issue #96)
# ---------------------------------------------------------------------------
#
# ``resolve_kernel``/``runtime_status`` above are what *this process* uses --
# they check PATH then fall straight through to ``managed_bin_dir()`` without
# needing anything at a fixed location. But humans and shell scripts
# (setup-hermes.sh, scripts/check-mcp-setup.sh, this repo's docs) all point
# at one fixed, documented path: ``~/.local/bin/simplicio``. When that shim
# is missing, or -- the actual bug reported in #96 -- is a symlink whose
# target no longer exists (a moved/rebuilt/cleaned managed install, a stale
# dev checkout), ``command -v simplicio`` in a fresh shell either finds
# nothing or finds a dangling link, even though this module would happily
# resolve the kernel from the managed dir. ``sync_canonical_symlink`` closes
# that gap idempotently.

_CANONICAL_DIR_ENV = "HERMES_CANONICAL_BIN_DIR"


def canonical_bin_dir() -> Path:
    """The documented, fixed PATH entry for the kernel shim.

    ``~/.local/bin`` on POSIX (honors ``HERMES_CANONICAL_BIN_DIR`` for
    tests/relocation). There is no equivalent fixed convention on Windows;
    callers should treat ``sys.platform == "win32"`` as a deliberate no-op.
    """
    override = os.environ.get(_CANONICAL_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "bin"


def canonical_symlink_path(lock: Optional[dict] = None) -> Path:
    """Full path of the canonical kernel shim, e.g. ``~/.local/bin/simplicio``."""
    lock = lock or load_runtime_lock()
    kernel = str(lock.get("kernel") or "simplicio")
    return canonical_bin_dir() / _bin_name(kernel)


def sync_canonical_symlink(
    status: Optional[RuntimeStatus] = None,
    lock: Optional[dict] = None,
) -> Optional[str]:
    """Idempotently point the canonical shim at the resolved kernel binary.

    Returns an error string describing what went wrong, or ``None`` on
    success *or* a legitimate no-op:

    * no kernel currently resolves (``status.present`` is False) -- nothing
      to link to yet; not an error, just "install the kernel first".
    * the shim already points at the resolved binary -- already in sync.

    Never overwrites a real file at the canonical path that merely happens
    not to already point at the resolved kernel (only ever replaces a
    symlink, or creates the path fresh) -- mirrors the "never clobber a
    user-managed install" rule ``ensure_runtime`` applies to the managed dir.
    """
    lock = lock or load_runtime_lock()
    status = status or runtime_status(lock)
    if not status.present or not status.bin_path:
        return None

    link = canonical_symlink_path(lock)
    target = Path(status.bin_path)
    resolved_target = str(target.resolve())

    if link.exists() and not link.is_symlink():
        if str(link.resolve()) == resolved_target:
            return None
        return (
            f"{link} exists and is a real file (not the managed symlink) -- "
            "refusing to overwrite it"
        )

    if link.is_symlink():
        try:
            current_target = str(link.resolve())
        except OSError:
            current_target = None
        if current_target == resolved_target:
            return None

    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    except OSError as exc:
        return f"failed to create canonical symlink {link}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Status + ensure
# ---------------------------------------------------------------------------


@dataclass
class RuntimeStatus:
    """One handshake result: what resolved, at what version, vs the pin."""

    bin_path: Optional[str]
    source: str  # env | path | managed | absent
    version: Optional[str]
    min_version: str
    satisfied: bool
    detail: str = ""
    lock_valid: bool = False
    release_repo: Optional[str] = None
    source_repo: Optional[str] = None
    target: Optional[str] = None
    asset_name: Optional[str] = None
    sha256: Optional[str] = None
    verified: bool = False
    reason_code: str = HANDSHAKE_REASON_READY
    handshake: RuntimeHandshake | None = None

    @property
    def present(self) -> bool:
        return self.bin_path is not None

    @property
    def ready(self) -> bool:
        """Alias for callers that want the readiness contract explicitly."""
        return self.satisfied

    def to_dict(self) -> dict:
        """Return the stable, JSON-safe readiness payload used by diagnostics."""
        return {
            "bin_path": self.bin_path,
            "source": self.source,
            "transport": self.source,
            "version": self.version,
            "min_version": self.min_version,
            "satisfied": self.satisfied,
            "detail": self.detail,
            "lock_valid": self.lock_valid,
            "repo": self.release_repo,
            "release_repo": self.release_repo,
            "source_repo": self.source_repo,
            "target": self.target,
            "asset_name": self.asset_name,
            "sha256": self.sha256,
            "verified": self.verified,
            "reason_code": self.reason_code,
            "handshake": self.handshake.to_dict() if self.handshake else None,
        }


def runtime_health(lock: Optional[dict] = None) -> dict:
    """Return the runtime status in the stable health/doctor shape.

    This is intentionally read-only.  CLI doctor can call ``doctor_status``
    when it wants the optional repair path, while status endpoints and the
    transport bridge can use this function without accidentally installing a
    binary.
    """
    status = runtime_status(lock)
    return {
        "schema": "simplicio-runtime/health/v1",
        "healthy": status.satisfied,
        "status": "healthy"
        if status.satisfied
        else ("stale" if status.present else "absent"),
        "bin_path": status.bin_path,
        "source": status.source,
        "transport": status.source,
        "version": status.version,
        "min_version": status.min_version,
        "repo": status.release_repo,
        "release_repo": status.release_repo,
        "source_repo": status.source_repo,
        "target": status.target,
        "asset_name": status.asset_name,
        "sha256": status.sha256,
        "verified": status.verified,
        "lock_valid": status.lock_valid,
        "detail": status.detail,
        "reason_code": status.reason_code,
        "handshake": status.handshake.to_dict() if status.handshake else None,
        "doctor_command": "simplicio-agent doctor --fix",
    }


def doctor_status(*, fix: bool = False) -> dict:
    """Return a JSON-safe health report for ``simplicio-agent doctor``.

    ``fix=False`` is a pure handshake.  ``fix=True`` delegates to the
    existing explicit-consent installer and reports its resulting state.
    Never raises so callers can render a diagnostic section reliably.
    """
    try:
        status = ensure_runtime(install=fix)
        report = {
            "schema": "simplicio-runtime/doctor/v1",
            "healthy": status.satisfied,
            "status": "healthy"
            if status.satisfied
            else ("stale" if status.present else "absent"),
            "bin_path": status.bin_path,
            "source": status.source,
            "transport": status.source,
            "version": status.version,
            "min_version": status.min_version,
            "repo": status.release_repo,
            "release_repo": status.release_repo,
            "source_repo": status.source_repo,
            "target": status.target,
            "asset_name": status.asset_name,
            "sha256": status.sha256,
            "verified": status.verified,
            "lock_valid": status.lock_valid,
            "detail": status.detail,
            "reason_code": status.reason_code,
            "handshake": status.handshake.to_dict() if status.handshake else None,
            "fixed": bool(fix and status.satisfied),
            "doctor_command": "simplicio-agent doctor --fix",
        }
        return report
    except Exception as exc:  # diagnostics must not take down the CLI
        return {
            "schema": "simplicio-runtime/doctor/v1",
            "healthy": False,
            "status": "error",
            "detail": str(exc),
            "reason_code": HANDSHAKE_REASON_HANDSHAKE_FAILED,
            "handshake": None,
            "fixed": False,
            "doctor_command": "simplicio-agent doctor --fix",
        }


def runtime_status(lock: Optional[dict] = None) -> RuntimeStatus:
    """Resolve, verify, and handshake the runtime as one readiness result."""
    lock = lock or load_runtime_lock()
    minimum = str(lock.get("min_version") or "0.0.0")
    validation = validate_runtime_lock(lock)
    if not validation.valid or not validation.stable_ready:
        detail = (
            f"runtime lock invalid: {validation.detail}"
            if not validation.valid
            else (
                "runtime lock signature is not verified: "
                f"{validation.signature_status}"
            )
        )
        release_repo = str(lock.get("release_repo") or "") or None
        source_repo = str(lock.get("source_repo") or "") or None
        return RuntimeStatus(
            bin_path=None,
            source="absent",
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=validation.valid,
            release_repo=release_repo,
            source_repo=source_repo,
            target=validation.target,
            reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
        )
    asset = validation.asset or {}
    asset_name = str(asset["name"])
    expected_sha256 = str(asset["sha256"])
    release_repo = str(lock.get("release_repo") or "") or None
    source_repo = str(lock.get("source_repo") or "") or None
    bin_path, source = resolve_kernel(lock)
    if not bin_path:
        detail = "kernel binary not found (env override, PATH, managed dir)"
        return RuntimeStatus(
            bin_path=None,
            source="absent",
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=True,
            release_repo=release_repo,
            source_repo=source_repo,
            target=validation.target,
            asset_name=asset_name,
            sha256=expected_sha256,
            reason_code=HANDSHAKE_REASON_RUNTIME_MISSING,
            handshake=build_runtime_handshake(
                lock=lock,
                runtime_version=None,
                min_runtime_version=minimum,
                bin_path=None,
                source="absent",
                healthy=False,
                reason_code=HANDSHAKE_REASON_RUNTIME_MISSING,
                reason_detail=detail,
            ),
        )
    try:
        actual_size = Path(bin_path).stat().st_size
    except OSError as exc:
        detail = f"runtime binary cannot be stat'ed: {exc}"
        return RuntimeStatus(
            bin_path=bin_path,
            source=source,
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=True,
            release_repo=release_repo,
            source_repo=source_repo,
            target=validation.target,
            asset_name=asset_name,
            sha256=expected_sha256,
            reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
            handshake=build_runtime_handshake(
                lock=lock,
                runtime_version=None,
                min_runtime_version=minimum,
                bin_path=bin_path,
                source=source,
                healthy=False,
                reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
                reason_detail=detail,
            ),
        )
    actual_sha256 = _sha256_file(Path(bin_path))
    if actual_sha256.lower() != expected_sha256.lower():
        detail = (
            f"runtime sha256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
        return RuntimeStatus(
            bin_path=bin_path,
            source=source,
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=True,
            release_repo=release_repo,
            source_repo=source_repo,
            target=validation.target,
            asset_name=asset_name,
            sha256=expected_sha256,
            reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
            handshake=build_runtime_handshake(
                lock=lock,
                runtime_version=None,
                min_runtime_version=minimum,
                bin_path=bin_path,
                source=source,
                healthy=False,
                reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
                reason_detail=detail,
            ),
        )
    if actual_size != asset["size"]:
        detail = f"runtime size mismatch: expected {asset['size']}, got {actual_size}"
        return RuntimeStatus(
            bin_path=bin_path,
            source=source,
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=True,
            target=validation.target,
            asset_name=asset_name,
            sha256=expected_sha256,
            reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
            handshake=build_runtime_handshake(
                lock=lock,
                runtime_version=None,
                min_runtime_version=minimum,
                bin_path=bin_path,
                source=source,
                healthy=False,
                reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
                reason_detail=detail,
            ),
        )
    version = kernel_version(bin_path)
    if version is None:
        detail = "binary resolved but --version handshake failed"
        return RuntimeStatus(
            bin_path=bin_path,
            source=source,
            version=None,
            min_version=minimum,
            satisfied=False,
            detail=detail,
            lock_valid=True,
            release_repo=release_repo,
            source_repo=source_repo,
            target=validation.target,
            asset_name=asset_name,
            sha256=expected_sha256,
            verified=True,
            reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
            handshake=build_runtime_handshake(
                lock=lock,
                runtime_version=None,
                min_runtime_version=minimum,
                bin_path=bin_path,
                source=source,
                healthy=False,
                reason_code=HANDSHAKE_REASON_HANDSHAKE_FAILED,
                reason_detail=detail,
            ),
        )
    ok = version_satisfies(version, minimum)
    detail = "" if ok else f"installed {version} < pinned {minimum}"
    reason_code = (
        HANDSHAKE_REASON_READY if ok else HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME
    )
    return RuntimeStatus(
        bin_path=bin_path,
        source=source,
        version=version,
        min_version=minimum,
        satisfied=ok,
        detail=detail,
        lock_valid=True,
        release_repo=release_repo,
        source_repo=source_repo,
        target=validation.target,
        asset_name=asset_name,
        sha256=expected_sha256,
        verified=True,
        reason_code=reason_code,
        handshake=build_runtime_handshake(
            lock=lock,
            runtime_version=version,
            min_runtime_version=minimum,
            bin_path=bin_path,
            source=source,
            healthy=ok,
            reason_code=reason_code,
            reason_detail=detail,
        ),
    )


def _asset_entry(lock: dict) -> tuple[Optional[str], Optional[str]]:
    """Map the current platform to ``(asset_name, pinned_sha256)``.

    Each value in ``assets`` may be a plain string (legacy shape, no pinned
    hash) or an object ``{"name": ..., "sha256": ...}``. Returns
    ``(None, None)`` when no asset is published for this platform.
    """
    assets = lock.get("assets") or {}
    entry = assets.get(_target_key())
    if entry is None:
        return None, None
    if isinstance(entry, dict):
        name = entry.get("name")
        sha256 = entry.get("sha256")
        return (str(name) if name else None), (str(sha256) if sha256 else None)
    return str(entry), None


def _platform_asset(lock: dict) -> Optional[str]:
    """Map the current platform to a release asset name, or None."""
    name, _ = _asset_entry(lock)
    return name


def _sha256_file(path: Path) -> str:
    """Streamed sha256 hex digest of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cleanup_tmp(tmp: Path) -> None:
    try:
        if tmp.is_file():
            tmp.unlink()
    except OSError as exc:
        logger.debug("failed to remove tmp download %s: %s", tmp, exc)


def _install_from_release(lock: dict, dest: Path) -> Optional[str]:
    """``gh release download`` the platform asset into ``dest``. Returns an
    error string on failure, None on success.

    Supply-chain gate (adversarial review #1): the downloaded bytes are
    hashed and compared against the ``sha256`` pinned in ``runtime.lock``
    for this asset. No pinned hash -> refuse to install rather than trust an
    unverified download; a mismatch -> delete the tmp file and error. The
    tmp file name is unique per-process (``pid``) to avoid a concurrent-
    download race clobbering another process's in-flight file, and is
    always removed on any failure path.
    """
    legacy_asset, legacy_sha256 = _asset_entry(lock)
    if legacy_asset and not legacy_sha256:
        return "no pinned sha256 for asset -- refusing unverified download"

    validation = validate_runtime_lock(lock)
    if not validation.valid or not validation.stable_ready:
        detail = validation.detail
        if "sha256" in detail or (legacy_asset and not legacy_sha256):
            detail += " (no pinned sha256 -- refusing unverified download)"
        if validation.valid and not validation.stable_ready:
            detail = f"signature is not verified: {validation.signature_status}"
        return f"runtime lock invalid: {detail}"
    entry = validation.asset or {}
    asset = str(entry["name"])
    pinned_sha256 = str(entry["sha256"])
    if not shutil.which("gh"):
        return "gh CLI not available for release download"
    repo = str(lock.get("release_repo") or "")
    tmp = dest.parent / f".{dest.name}.download.{os.getpid()}"
    try:
        proc = subprocess.run(
            [
                "gh",
                "release",
                "download",
                f"v{entry['version']}",
                "--repo",
                repo,
                "--pattern",
                asset,
                "--output",
                str(tmp),
                "--clobber",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _cleanup_tmp(tmp)
        return f"gh release download failed to run: {exc}"
    if proc.returncode != 0:
        _cleanup_tmp(tmp)
        return f"gh release download failed: {(proc.stderr or '').strip()[:300]}"
    if not tmp.is_file():
        _cleanup_tmp(tmp)
        return f"gh release download reported success but {tmp} is missing"

    digest = _sha256_file(tmp)
    if digest.lower() != pinned_sha256.lower():
        _cleanup_tmp(tmp)
        return f"sha256 mismatch for {asset}: expected {pinned_sha256}, got {digest}"
    expected_size = int(entry["size"])
    actual_size = tmp.stat().st_size
    if actual_size != expected_size:
        _cleanup_tmp(tmp)
        return f"size mismatch for {asset}: expected {expected_size}, got {actual_size}"

    try:
        tmp.chmod(0o755)
        tmp.replace(dest)
    except OSError as exc:
        _cleanup_tmp(tmp)
        return f"failed to move downloaded binary into place: {exc}"
    return None


def _install_from_pinned_url(lock: dict, dest: Path) -> Optional[str]:
    """Download and verify the target at its immutable lock URL.

    The public Simplicio distribution currently tracks platform binaries at
    version tags before every GitHub release asset is promoted. This path is
    therefore a bootstrap fallback, never an unverified fallback: URL,
    SHA-256, and byte size are all required by the same lock validator used by
    the release path.
    """
    validation = validate_runtime_lock(lock)
    if not validation.valid or not validation.stable_ready:
        detail = validation.detail
        if validation.valid and not validation.stable_ready:
            detail = f"signature is not verified: {validation.signature_status}"
        return f"runtime lock invalid: {detail}"
    entry = validation.asset or {}
    url = str(entry["url"])
    pinned_sha256 = str(entry["sha256"])
    expected_size = int(entry["size"])
    tmp = dest.parent / f".{dest.name}.url-download.{os.getpid()}"
    try:
        request = Request(url, headers={"User-Agent": "simplicio-agent-runtime-bootstrap"})
        with urlopen(request, timeout=300) as response, tmp.open("wb") as output:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                output.write(chunk)
    except Exception as exc:
        _cleanup_tmp(tmp)
        return f"pinned asset download failed: {exc}"

    digest = _sha256_file(tmp)
    actual_size = tmp.stat().st_size
    if digest.lower() != pinned_sha256.lower():
        _cleanup_tmp(tmp)
        return f"sha256 mismatch for {entry['name']}: expected {pinned_sha256}, got {digest}"
    if actual_size != expected_size:
        _cleanup_tmp(tmp)
        return f"size mismatch for {entry['name']}: expected {expected_size}, got {actual_size}"
    try:
        tmp.chmod(0o755)
        tmp.replace(dest)
    except OSError as exc:
        _cleanup_tmp(tmp)
        return f"failed to move downloaded binary into place: {exc}"
    return None


def _install_from_sibling(lock: dict, dest: Path) -> Optional[str]:
    """``cargo build --release`` in the sibling checkout, then copy the
    binary into ``dest``. Returns an error string on failure, None on
    success. This is the only install path on Windows."""
    sibling = (
        repo_root() / str(lock.get("sibling_checkout") or "../simplicio-runtime")
    ).resolve()
    if not (sibling / "Cargo.toml").is_file():
        return f"sibling checkout not found at {sibling}"
    if not shutil.which("cargo"):
        return "cargo not available to build from the sibling checkout"
    try:
        proc = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(sibling),
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cargo build failed to run: {exc}"
    if proc.returncode != 0:
        return f"cargo build failed: {(proc.stderr or '').strip()[-300:]}"
    built = (
        sibling
        / "target"
        / "release"
        / _bin_name(str(lock.get("kernel") or "simplicio"))
    )
    if not built.is_file():
        return f"cargo build succeeded but binary not found at {built}"
    try:
        shutil.copy2(built, dest)
        dest.chmod(0o755)
    except OSError as exc:
        return f"failed to copy built binary into place: {exc}"
    return None


_bootstrap_ran = False


def bootstrap_session() -> Optional[str]:
    """Once-per-process startup handshake (ADR-0003).

    The agent always runs *with* the runtime: this is called at chat
    startup so an absent/stale kernel is surfaced immediately instead of
    execution bindings failing closed with no explanation mid-turn.

    This performs the ``--version`` handshake only -- it **never**
    downloads or builds anything (adversarial review #1c: an unattended
    network fetch at every chat startup is a supply-chain and latency
    hazard the user never consented to). Installing/updating the kernel is
    exclusively ``ensure_runtime(install=True)``, reached via
    ``simplicio-agent doctor --fix`` -- that command *is* the explicit consent.
    Returns a one-line warning (with the doctor fix instruction) for the
    caller to print, or ``None`` when the kernel is healthy. Never raises,
    never blocks startup on anything beyond the local handshake.
    """
    global _bootstrap_ran
    if _bootstrap_ran:
        return None
    _bootstrap_ran = True

    try:
        lock = load_runtime_lock()
        status = runtime_status(lock)
        if status.satisfied:
            return None

        where = f" ({status.bin_path} [{status.source}])" if status.present else ""
        return (
            f"simplicio kernel unavailable: {status.detail or 'not found'}{where} "
            f"-- pinned >= {status.min_version}. Run 'simplicio-agent doctor --fix' to "
            "install/update it."
        )
    except Exception as exc:  # startup must never crash on the handshake
        logger.debug("runtime bootstrap failed: %s", exc)
        return None


def reset_bootstrap() -> None:
    """Clear the once-per-process bootstrap latch. Test-only escape hatch."""
    global _bootstrap_ran
    _bootstrap_ran = False


def ensure_runtime(*, install: bool = False) -> RuntimeStatus:
    """Handshake and (optionally) install/update the managed kernel.

    With ``install=False`` this is a pure status check. With
    ``install=True`` and an unsatisfied pin, it tries the release download
    then the sibling cargo build, installing into ``~/.simplicio/bin``, and
    re-handshakes. Never raises; failures land in ``status.detail``.
    """
    lock = load_runtime_lock()
    status = runtime_status(lock)
    if status.satisfied or not install:
        return status

    validation = validate_runtime_lock(lock)
    if not validation.valid or not validation.stable_ready:
        status.detail = f"runtime lock invalid: {validation.detail}"
        if validation.valid and not validation.stable_ready:
            status.detail = (
                "runtime lock signature is not verified: "
                f"{validation.signature_status}"
            )
        return status

    # Never overwrite a user-managed install (env/PATH) — the managed dir
    # is the only place this module writes to. A stale PATH kernel is
    # reported, not replaced behind the user's back.
    if status.source in ("env", "path") and status.present:
        status.detail += (
            " — resolved kernel is user-managed; update it in place or "
            "remove it so the managed install takes over"
        )
        return status

    dest_dir = managed_bin_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        status.detail = f"cannot create managed dir {dest_dir}: {exc}"
        return status
    dest = dest_dir / _bin_name(str(lock.get("kernel") or "simplicio"))

    developer_build = os.environ.get(_DEV_BUILD_ENV, "").strip() == "1"
    strategies = [_install_from_release, _install_from_pinned_url]
    if developer_build:
        strategies.append(_install_from_sibling)
    errors = []
    for strategy in strategies:
        err = strategy(lock, dest)
        if err is None:
            # The install changed what's on disk at the managed path -- the
            # kernel_binding layer caches PATH resolution + the verified
            # handshake per process (adversarial review #5), so without an
            # explicit invalidation it would keep reporting the pre-install
            # state for the rest of the process lifetime.
            _reset_kernel_binding_cache()
            refreshed = runtime_status(lock)
            if not refreshed.satisfied and refreshed.present:
                refreshed.detail = (
                    f"installed via {strategy.__name__} but handshake still "
                    f"unsatisfied: {refreshed.detail}"
                )
            return refreshed
        errors.append(err)

    if not developer_build:
        errors.append(
            f"developer sibling build disabled; set {_DEV_BUILD_ENV}=1 explicitly"
        )
    status.detail = "install failed: " + "; ".join(errors)
    return status


def _reset_kernel_binding_cache() -> None:
    """Best-effort invalidation of ``tools.kernel_binding``'s process caches
    after this module installs/updates the managed kernel. Import is local
    (kernel_binding imports back into this module) and tolerant of any
    failure -- a stale cache is a staleness bug, not a crash."""
    try:
        from tools.kernel_binding import reset_kernel_cache

        reset_kernel_cache()
    except Exception as exc:
        logger.debug("failed to reset kernel_binding cache after install: %s", exc)
