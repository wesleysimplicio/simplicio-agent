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

import hashlib
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

# Identity handshake (adversarial review #4): a bare X.Y.Z found *anywhere*
# in the output is not enough -- PATH collisions and homonym binaries (e.g.
# an unrelated "Simplicio Agent v0.17.0" banner) must never be mistaken for
# the kernel. Anchored at the start of stdout only (never stderr, which can
# carry unrelated warnings); allows leading whitespace and an optional
# "-runtime" / "v" decoration.
_KERNEL_BANNER_RE = re.compile(
    r"^\s*simplicio(?:-runtime)?\s+v?(\d+)\.(\d+)\.(\d+)",
    re.IGNORECASE,
)

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
    """Run ``<bin> --version`` and return the raw semver string, or None.

    Validates *identity*, not just presence of a version-shaped substring:
    ``stdout`` must start with a ``simplicio``/``simplicio-runtime`` banner
    (see ``_KERNEL_BANNER_RE``). A binary that merely shares the name but
    prints an unrelated banner (or puts its version only in stderr) does not
    satisfy the handshake and returns ``None``.
    """
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
    m = _KERNEL_BANNER_RE.match(proc.stdout or "")
    if not m:
        return None
    return f"{int(m.group(1))}.{int(m.group(2))}.{int(m.group(3))}"


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


def _asset_entry(lock: dict) -> tuple[Optional[str], Optional[str]]:
    """Map the current platform to ``(asset_name, pinned_sha256)``.

    Each value in ``assets`` may be a plain string (legacy shape, no pinned
    hash) or an object ``{"name": ..., "sha256": ...}``. Returns
    ``(None, None)`` when no asset is published for this platform.
    """
    assets = lock.get("assets") or {}
    system = platform.system().lower()      # darwin / linux / windows
    machine = platform.machine().lower()    # arm64 / x86_64 / amd64
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    entry = assets.get(f"{system}-{machine}")
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
    asset, pinned_sha256 = _asset_entry(lock)
    if not asset:
        return f"no release asset published for this platform ({platform.system()}-{platform.machine()})"
    if not pinned_sha256:
        return "no pinned sha256 for asset -- refusing unverified download"
    if not shutil.which("gh"):
        return "gh CLI not available for release download"
    repo = str(lock.get("release_repo") or "")
    tmp = dest.parent / f".{dest.name}.download.{os.getpid()}"
    try:
        proc = subprocess.run(
            ["gh", "release", "download", "--repo", repo,
             "--pattern", asset, "--output", str(tmp), "--clobber"],
            capture_output=True, text=True, timeout=300,
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
