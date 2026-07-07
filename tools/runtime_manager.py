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

* ``gh release download`` of the platform asset from the release repo
  (macOS/Linux — the release pipeline publishes those).
* ``cargo build --release`` from the sibling ``simplicio-runtime`` checkout
  (the only path on Windows, which has no published binary asset).

Everything degrades honestly: no strategy available -> a status object that
says exactly what is missing and how to fix it. Nothing here raises into a
conversation turn.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOCK_FILENAME = "runtime.lock"
_KERNEL_BIN_ENV = "HERMES_KERNEL_BIN"
_MANAGED_DIR_ENV = "SIMPLICIO_HOME"

_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_DEFAULT_LOCK = {
    "schema": "runtime-lock/v1",
    "kernel": "simplicio",
    "min_version": "0.0.0",
    "release_repo": "wesleysimplicio/simplicio",
    "source_repo": "wesleysimplicio/simplicio-runtime",
    "assets": {},
    "sibling_checkout": "../simplicio-runtime",
}


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------

def repo_root() -> Path:
    """The simplicio-agent repo root (parent of ``tools/``)."""
    return Path(__file__).resolve().parent.parent


def load_runtime_lock() -> dict:
    """Read ``runtime.lock`` from the repo root.

    Returns the parsed dict merged over safe defaults. A missing or corrupt
    lock degrades to a ``min_version`` of ``0.0.0`` (any kernel satisfies),
    matching the pre-lock behavior — never raises.
    """
    lock_path = repo_root() / _LOCK_FILENAME
    merged = dict(_DEFAULT_LOCK)
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            merged.update({k: v for k, v in raw.items() if v is not None})
    except FileNotFoundError:
        logger.debug("runtime.lock not found at %s -- using defaults", lock_path)
    except Exception as exc:
        logger.warning("runtime.lock unreadable (%s) -- using defaults", exc)
    return merged


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
    """Run ``<bin> --version`` and return the raw semver string, or None."""
    try:
        from hermes_cli._subprocess_compat import IS_WINDOWS, windows_hide_flags
        extra = {"creationflags": windows_hide_flags()} if IS_WINDOWS else {}
    except Exception:
        extra = {}
    try:
        proc = subprocess.run(
            [bin_path, "--version"],
            capture_output=True, text=True, timeout=10, **extra,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("kernel --version failed for %s: %s", bin_path, exc)
        return None
    if proc.returncode != 0:
        return None
    triple = parse_semver((proc.stdout or "") + (proc.stderr or ""))
    return ".".join(str(n) for n in triple) if triple else None


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
# Status + ensure
# ---------------------------------------------------------------------------

@dataclass
class RuntimeStatus:
    """One handshake result: what resolved, at what version, vs the pin."""

    bin_path: Optional[str]
    source: str                 # env | path | managed | absent
    version: Optional[str]
    min_version: str
    satisfied: bool
    detail: str = ""

    @property
    def present(self) -> bool:
        return self.bin_path is not None


def runtime_status(lock: Optional[dict] = None) -> RuntimeStatus:
    """Handshake the resolved kernel against the ``runtime.lock`` pin."""
    lock = lock or load_runtime_lock()
    minimum = str(lock.get("min_version") or "0.0.0")
    bin_path, source = resolve_kernel(lock)
    if not bin_path:
        return RuntimeStatus(
            bin_path=None, source="absent", version=None,
            min_version=minimum, satisfied=False,
            detail="kernel binary not found (env override, PATH, managed dir)",
        )
    version = kernel_version(bin_path)
    if version is None:
        return RuntimeStatus(
            bin_path=bin_path, source=source, version=None,
            min_version=minimum, satisfied=False,
            detail="binary resolved but --version handshake failed",
        )
    ok = version_satisfies(version, minimum)
    return RuntimeStatus(
        bin_path=bin_path, source=source, version=version,
        min_version=minimum, satisfied=ok,
        detail="" if ok else f"installed {version} < pinned {minimum}",
    )


def _platform_asset(lock: dict) -> Optional[str]:
    """Map the current platform to a release asset name, or None."""
    assets = lock.get("assets") or {}
    system = platform.system().lower()      # darwin / linux / windows
    machine = platform.machine().lower()    # arm64 / x86_64 / amd64
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    return assets.get(f"{system}-{machine}")


def _install_from_release(lock: dict, dest: Path) -> Optional[str]:
    """``gh release download`` the platform asset into ``dest``. Returns an
    error string on failure, None on success."""
    asset = _platform_asset(lock)
    if not asset:
        return f"no release asset published for this platform ({platform.system()}-{platform.machine()})"
    if not shutil.which("gh"):
        return "gh CLI not available for release download"
    repo = str(lock.get("release_repo") or "")
    tmp = dest.parent / f".{dest.name}.download"
    try:
        proc = subprocess.run(
            ["gh", "release", "download", "--repo", repo,
             "--pattern", asset, "--output", str(tmp), "--clobber"],
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"gh release download failed to run: {exc}"
    if proc.returncode != 0:
        return f"gh release download failed: {(proc.stderr or '').strip()[:300]}"
    try:
        tmp.chmod(0o755)
        tmp.replace(dest)
    except OSError as exc:
        return f"failed to move downloaded binary into place: {exc}"
    return None


def _install_from_sibling(lock: dict, dest: Path) -> Optional[str]:
    """``cargo build --release`` in the sibling checkout, then copy the
    binary into ``dest``. Returns an error string on failure, None on
    success. This is the only install path on Windows."""
    sibling = (repo_root() / str(lock.get("sibling_checkout") or "../simplicio-runtime")).resolve()
    if not (sibling / "Cargo.toml").is_file():
        return f"sibling checkout not found at {sibling}"
    if not shutil.which("cargo"):
        return "cargo not available to build from the sibling checkout"
    try:
        proc = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(sibling), capture_output=True, text=True, timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cargo build failed to run: {exc}"
    if proc.returncode != 0:
        return f"cargo build failed: {(proc.stderr or '').strip()[-300:]}"
    built = sibling / "target" / "release" / _bin_name(str(lock.get("kernel") or "simplicio"))
    if not built.is_file():
        return f"cargo build succeeded but binary not found at {built}"
    try:
        shutil.copy2(built, dest)
        dest.chmod(0o755)
    except OSError as exc:
        return f"failed to copy built binary into place: {exc}"
    return None


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

    errors = []
    for strategy in (_install_from_release, _install_from_sibling):
        err = strategy(lock, dest)
        if err is None:
            refreshed = runtime_status(lock)
            if not refreshed.satisfied and refreshed.present:
                refreshed.detail = (
                    f"installed via {strategy.__name__} but handshake still "
                    f"unsatisfied: {refreshed.detail}"
                )
            return refreshed
        errors.append(err)

    status.detail = "install failed: " + "; ".join(errors)
    return status
