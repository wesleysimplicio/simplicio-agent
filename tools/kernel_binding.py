"""Binding to the simplicio-runtime kernel (the ``simplicio`` binary).

Part of F2 (issue #20): make ``simplicio`` the deterministic spine of the
conversation loop for the pieces that don't need an LLM — action gating,
checkpoints, mechanical edits, orient/recall, and evidence.

This module is the **detection + subprocess client** shared by every
binding. Individual bindings (action gate, checkpoint mirror, mechanical
edit, orient, ledger) live as thin call sites in the modules they augment
(``tools/approval.py`` for the gate, etc.) and import from here.

Design rules (see AGENTS.md "core is a narrow waist" + the issue body):

* **Never reimplement the kernel.** We only ever shell out to the
  ``simplicio`` binary resolved from PATH (or ``HERMES_KERNEL_BIN``).
* **Honest degradation.** No kernel on PATH -> the feature is OFF with an
  explicit log line. We never fabricate a kernel decision.
* **Fail-closed is opt-in, not ambient.** ``mode="required"`` blocks risky
  actions when the kernel is absent; the default ``mode="auto"`` degrades to
  the existing (pre-#20) behavior so installations without the kernel see
  zero behavior change.
* **Cache-safe.** Everything here happens in the tool layer, never touches
  the system prompt mid-conversation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_KERNEL_BIN_ENV = "HERMES_KERNEL_BIN"
_DEFAULT_KERNEL_BIN = "simplicio"

# Cache the PATH lookup for the process lifetime -- shutil.which() does a
# filesystem stat per PATH entry and this is checked on every guarded tool
# call once a binding is enabled.
_kernel_path_cache: dict[str, Optional[str]] = {}


class KernelBindingError(RuntimeError):
    """The kernel binary was invoked but the call failed (non-zero exit,
    timeout, or output that isn't the JSON the binding contract expects)."""


def _kernel_bin_name() -> str:
    """The kernel binary name, sourced from ``runtime.lock`` (single source
    of truth -- ADR-0003 adversarial review #9), falling back to the
    literal ``simplicio`` if the lock can't be read."""
    try:
        from tools.runtime_manager import load_runtime_lock
        return str(load_runtime_lock().get("kernel") or _DEFAULT_KERNEL_BIN)
    except Exception as exc:
        logger.debug("failed to read kernel bin name from runtime.lock: %s", exc)
        return _DEFAULT_KERNEL_BIN


def resolve_kernel_bin() -> Optional[str]:
    """Return the absolute path to the ``simplicio`` binary, or ``None``.

    Honors ``HERMES_KERNEL_BIN`` for tests/overrides; otherwise resolves the
    bare kernel command (name from ``runtime.lock``) from PATH, then falls
    back to the managed install dir (``~/.simplicio/bin``, populated by
    ``tools/runtime_manager.ensure_runtime`` — see ADR-0003). The agent
    resolves the kernel, it never reimplements it.
    """
    override = os.environ.get(_KERNEL_BIN_ENV, "").strip()
    bin_name = override or _kernel_bin_name()
    if bin_name in _kernel_path_cache:
        return _kernel_path_cache[bin_name]
    resolved = shutil.which(bin_name)
    if resolved is None and not override:
        try:
            from tools.runtime_manager import managed_bin_dir
            candidate = managed_bin_dir() / (
                f"{bin_name}.exe" if os.name == "nt" else bin_name
            )
            if candidate.is_file() and os.access(candidate, os.X_OK):
                resolved = str(candidate)
        except Exception as exc:
            logger.debug("managed kernel dir lookup failed: %s", exc)
    _kernel_path_cache[bin_name] = resolved
    return resolved


def is_kernel_available() -> bool:
    """True when the ``simplicio`` kernel binary is resolvable on PATH."""
    return resolve_kernel_bin() is not None


_kernel_verified_cache: Optional[tuple[bool, str]] = None


def _kernel_verified() -> tuple[bool, str]:
    """``(ok, detail)`` -- presence **and** pin handshake, cached per process.

    Execution-class bindings (gate, mechanical edit) must never talk to a
    binary that merely *shares the kernel's name*: PATH collisions are real
    (pip shims, branding aliases). ``ok`` means runtime_manager resolved a
    binary whose ``--version`` satisfies the ``runtime.lock`` pin.

    When ``runtime_manager`` itself is unavailable (import failure or an
    unexpected exception from the handshake), this fails **closed** --
    ``(False, "runtime_manager unavailable: <error>")`` -- rather than
    degrading to a presence-only check (adversarial review #3). A broken
    dependency-manager module is not evidence the kernel is safe to trust;
    honest degradation here would silently reopen the PATH-collision hole
    ADR-0003 closed. The failure is logged at ``warning`` since it is an
    operational anomaly, not routine absence.
    """
    global _kernel_verified_cache
    if _kernel_verified_cache is not None:
        return _kernel_verified_cache
    try:
        from tools.runtime_manager import runtime_status
        st = runtime_status()
        _kernel_verified_cache = (st.satisfied, st.detail or "")
    except Exception as exc:
        logger.warning("runtime_manager unavailable, failing closed: %s", exc)
        _kernel_verified_cache = (False, f"runtime_manager unavailable: {exc}")
    return _kernel_verified_cache


def reset_kernel_cache() -> None:
    """Clear the PATH-resolution + handshake caches. Test-only escape hatch."""
    global _kernel_verified_cache
    _kernel_path_cache.clear()
    _kernel_verified_cache = None


def _run_kernel(
    args: list[str],
    *,
    timeout: float = 10.0,
    input_data: Optional[str] = None,
) -> dict:
    """Run ``simplicio <args>`` and parse a JSON object from stdout.

    Raises:
        KernelBindingError: binary missing, non-zero exit, timeout, or
            stdout isn't valid JSON. Callers decide the fail-open/closed
            policy -- this function only reports what happened.
    """
    kernel_bin = resolve_kernel_bin()
    if not kernel_bin:
        raise KernelBindingError(f"kernel binary '{_DEFAULT_KERNEL_BIN}' not found on PATH")

    try:
        from hermes_cli._subprocess_compat import IS_WINDOWS, windows_hide_flags
        extra_kwargs = {"creationflags": windows_hide_flags()} if IS_WINDOWS else {}
    except Exception:
        extra_kwargs = {}

    try:
        proc = subprocess.run(
            [kernel_bin, *args],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            **extra_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise KernelBindingError(f"kernel call timed out after {timeout}s: {args[:2]}") from exc
    except OSError as exc:
        raise KernelBindingError(f"kernel call failed to start: {exc}") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise KernelBindingError(
            f"kernel exited {proc.returncode} for {args[:2]}: {stderr or '(no stderr)'}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return {}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise KernelBindingError(
            f"kernel returned non-JSON output for {args[:2]}: {stdout[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise KernelBindingError(
            f"kernel returned a JSON {type(parsed).__name__}, expected an object: {args[:2]}"
        )
    return parsed


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_VALID_MODES = ("auto", "required", "off")

# Per-binding default modes (ADR-0003): the agent always runs with the
# runtime, so execution-class bindings fail closed by default -- a missing
# or broken kernel blocks flagged-dangerous execution instead of silently
# falling back. Read-class bindings (orient, recall) and evidence mirrors
# (checkpoint, ledger) keep honest degradation: their absence never
# compromises safety, only enrichment. config.yaml still overrides any of
# these per binding.
_BINDING_DEFAULT_MODES = {
    "action_gate": "required",
    "mechanical_edit": "required",
}
_FALLBACK_DEFAULT_MODE = "auto"


def _default_mode(binding: str) -> str:
    return _BINDING_DEFAULT_MODES.get(binding, _FALLBACK_DEFAULT_MODE)


def _normalize_mode(mode: Any, default: str = _FALLBACK_DEFAULT_MODE) -> str:
    """Normalize a ``kernel_binding.<binding>.mode`` config value.

    Mirrors ``tools.approval._normalize_approval_mode``: YAML 1.1 parses
    bare ``off`` as ``False``, so booleans are folded in too. Unknown or
    non-string values fall back to the binding's own default.
    """
    if isinstance(mode, bool):
        return "off" if mode is False else default
    if isinstance(mode, str):
        normalized = mode.strip().lower()
        if normalized in _VALID_MODES:
            return normalized
        if normalized:
            logger.warning(
                "Unknown kernel_binding mode %r -- defaulting to %r. Valid values: %s",
                mode, default, ", ".join(_VALID_MODES),
            )
    return default


def get_binding_config(binding: str) -> dict:
    """Read ``kernel_binding.<binding>`` from config.yaml.

    Returns ``{"mode": "auto"|"required"|"off"}`` merged with any extra
    keys the binding defines. Never raises -- config load failures degrade
    to the binding's default mode (``required`` for execution bindings,
    ``auto`` otherwise -- see ``_BINDING_DEFAULT_MODES``).
    """
    default = _default_mode(binding)
    try:
        from hermes_cli.config import cfg_get, load_config
        config = load_config()
        raw = cfg_get(config, "kernel_binding", binding, default={}) or {}
    except Exception as exc:
        logger.debug("Failed to load kernel_binding.%s config: %s", binding, exc)
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = dict(raw)
    out["mode"] = _normalize_mode(raw.get("mode", default), default)
    return out


# ---------------------------------------------------------------------------
# Telemetry -- savings-event/v1 (dogfooding runtime#2775)
# ---------------------------------------------------------------------------

_TELEMETRY_ENV = "HERMES_KERNEL_BINDING_LOG"
_TELEMETRY_REL = Path(".hermes") / "telemetry" / "kernel_binding.jsonl"


def _telemetry_log_path() -> Path:
    override = os.environ.get(_TELEMETRY_ENV)
    return Path(override).expanduser() if override else Path.home() / _TELEMETRY_REL


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class SavingsEvent:
    """``savings-event/v1`` -- one kernel-binding decision, for telemetry.

    ``source`` is one of ``mechanical_edit`` | ``recall`` | ``gate`` per the
    issue's AC. ``outcome`` is free text (e.g. ``kernel_absent_degraded``,
    ``blocked_kernel_absent``, ``kernel_denied``, ``kernel_allowed``).
    """

    schema: str = "savings-event/v1"
    source: str = "gate"
    outcome: str = "unknown"
    detail: str = ""
    ts: str = field(default_factory=_utc_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)


def emit_savings_event(source: str, outcome: str, detail: str = "") -> None:
    """Append a ``savings-event/v1`` record. Never raises -- telemetry is
    best-effort and must not affect the gate/edit/recall decision itself."""
    try:
        path = _telemetry_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = SavingsEvent(source=source, outcome=outcome, detail=detail[:300])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")
    except Exception as exc:
        logger.debug("Failed to emit kernel-binding savings event: %s", exc)


# ---------------------------------------------------------------------------
# Binding 1 -- Action Gate
# ---------------------------------------------------------------------------

def evaluate_action_gate(
    command: str,
    *,
    pattern_key: str = "",
    description: str = "",
    session_key: str = "",
) -> Optional[dict]:
    """Front-end ``tools/approval.py`` to the kernel's ``gate classify``.

    Called only for commands the existing (legacy) detector already flagged
    as dangerous -- this binding never widens what's considered risky, it
    only ever *adds* a block on top of the existing approval flow, or
    defers to it. It never auto-approves on the kernel's say-so; that would
    weaken, not front-end, the existing safety net.

    Returns:
        ``None`` -- defer to the legacy approval flow unchanged.
        ``dict`` -- ``{"approved": False, "message": ..., ...}`` -- block
        the command before the legacy flow even runs (fail-closed or an
        explicit kernel denial).
    """
    cfg = get_binding_config("action_gate")
    mode = cfg["mode"]
    if mode == "off":
        return None

    kernel_ok, kernel_detail = _kernel_verified()
    if not kernel_ok:
        why = kernel_detail or "kernel binary not found"
        if mode == "required":
            emit_savings_event(
                "gate", "blocked_kernel_absent",
                f"pattern={pattern_key} description={description} why={why}",
            )
            return {
                "approved": False,
                "pattern_key": pattern_key,
                "description": description,
                "message": (
                    "BLOCKED: kernel_binding.action_gate.mode is 'required' but no "
                    f"healthy simplicio kernel is available ({why}). Refusing to fall "
                    "back to an ungated approval for a flagged-dangerous command "
                    f"({description or pattern_key}). Run 'hermes doctor --fix' to "
                    "install/update the kernel, or set "
                    "kernel_binding.action_gate.mode to 'auto'/'off' to change this."
                ),
            }
        logger.warning(
            "kernel_binding.action_gate: no healthy simplicio kernel (%s) -- "
            "gate is OFF for this call, falling back to the built-in approval flow "
            "(honest degradation, not a silent bypass).", why,
        )
        return None

    try:
        result = _run_kernel(
            [
                "gate", "classify",
                "--action", command,
                "--json",
            ],
            timeout=8.0,
        )
    except KernelBindingError as exc:
        logger.warning("kernel_binding.action_gate: gate classify failed: %s", exc)
        if mode == "required":
            emit_savings_event("gate", "blocked_kernel_error", str(exc)[:300])
            return {
                "approved": False,
                "pattern_key": pattern_key,
                "description": description,
                "message": (
                    "BLOCKED: kernel_binding.action_gate.mode is 'required' and the "
                    f"kernel gate call failed ({exc}). Refusing to approve a "
                    f"flagged-dangerous command ({description or pattern_key}) without it."
                ),
            }
        return None

    decision = str(result.get("decision", "")).strip().lower()
    if decision in {"deny", "block", "blocked"}:
        reason = str(result.get("reason") or result.get("message") or "kernel denied")
        emit_savings_event("gate", "kernel_denied", reason[:300])
        return {
            "approved": False,
            "pattern_key": pattern_key,
            "description": description,
            "message": f"BLOCKED by simplicio kernel action gate: {reason}",
        }

    emit_savings_event("gate", f"kernel_{decision or 'observed'}", command[:200])
    return None


# ---------------------------------------------------------------------------
# Binding 2 -- Checkpoint mirroring (wrapper, not replacement -- see
# docs/architecture/ADR-0001-kernel-checkpoint-binding.md)
# ---------------------------------------------------------------------------

def mirror_checkpoint(label: str, *, workdir: str = "", extra: Optional[dict] = None) -> None:
    """Best-effort mirror of a ``tools/checkpoint_manager`` snapshot into the
    kernel's evidence ledger. Never raises, never blocks the real
    (git-shadow-store) checkpoint -- see the ADR for why the kernel does not
    own the snapshot mechanism."""
    cfg = get_binding_config("checkpoint")
    if cfg["mode"] == "off" or not is_kernel_available():
        if cfg["mode"] != "off":
            logger.debug("kernel_binding.checkpoint: kernel not found on PATH, skipping mirror")
        return
    try:
        payload = {"label": label, "workdir": workdir, **(extra or {})}
        _run_kernel(
            ["checkpoint", "record", "--json"],
            timeout=5.0,
            input_data=json.dumps(payload),
        )
        emit_savings_event("gate", "checkpoint_mirrored", label[:200])
    except KernelBindingError as exc:
        logger.debug("kernel_binding.checkpoint: mirror failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Binding 3 -- Mechanical edit plan
# ---------------------------------------------------------------------------

def edit_mechanical(plan: dict) -> Optional[dict]:
    """Submit a deterministic edit plan to ``simplicio edit --json``.

    ``plan`` follows the runtime's edit-plan contract (``file`` +
    ``operations``: replace/replace_all/insert_before/insert_after/
    replace_line/delete_line/append/prepend). Returns the kernel's result
    dict, or ``None`` when the binding is off/unavailable -- callers must
    fall back to an LLM-authored edit in that case (never fabricate a
    mechanical-edit success).
    """
    cfg = get_binding_config("mechanical_edit")
    if cfg["mode"] == "off":
        return None
    kernel_ok, kernel_detail = _kernel_verified()
    if not kernel_ok:
        msg = (
            "kernel_binding.mechanical_edit: no healthy kernel "
            f"({kernel_detail or 'not found'})"
        )
        if cfg["mode"] == "required":
            raise KernelBindingError(msg)
        logger.warning("%s -- falling back to LLM-authored edit", msg)
        return None
    try:
        result = _run_kernel(
            ["edit", json.dumps(plan), "--json"],
            timeout=15.0,
        )
    except KernelBindingError as exc:
        emit_savings_event("mechanical_edit", "kernel_error", str(exc)[:300])
        if cfg["mode"] == "required":
            raise
        logger.warning("kernel_binding.mechanical_edit: edit call failed, falling back: %s", exc)
        return None
    emit_savings_event("mechanical_edit", "applied", plan.get("file", "")[:300])
    return result


# ---------------------------------------------------------------------------
# Binding 4 -- Orient + recall
# ---------------------------------------------------------------------------

def orient_map(repo: str, *, fmt: str = "markdown") -> Optional[str]:
    """``simplicio runtime map --repo <repo> --for-llm <fmt>`` -- a
    compressed repo view for context_engine/coding_context instead of raw
    tree reads. Returns ``None`` on any degradation (off/absent/error)."""
    cfg = get_binding_config("orient")
    if cfg["mode"] == "off" or not is_kernel_available():
        return None
    try:
        result = _run_kernel(
            ["runtime", "map", "--repo", repo, "--for-llm", fmt, "--json"],
            timeout=20.0,
        )
    except KernelBindingError as exc:
        logger.debug("kernel_binding.orient: map failed (non-fatal): %s", exc)
        return None
    emit_savings_event("recall", "orient_map", repo[:300])
    return result.get("map") or result.get("output") or None


def memory_recall(query: str, *, repo: str = "") -> Optional[str]:
    """``simplicio memory <query> --json`` -- prior decisions/context from
    the kernel's neural memory instead of re-deriving known facts."""
    cfg = get_binding_config("recall")
    if cfg["mode"] == "off" or not is_kernel_available():
        return None
    args = ["memory", query, "--json"]
    if repo:
        args += ["--repo", repo]
    try:
        result = _run_kernel(args, timeout=10.0)
    except KernelBindingError as exc:
        logger.debug("kernel_binding.recall: memory query failed (non-fatal): %s", exc)
        return None
    emit_savings_event("recall", "memory_hit", query[:300])
    return result.get("result") or result.get("output") or None


# ---------------------------------------------------------------------------
# Binding 6 -- Evidence ledger
# ---------------------------------------------------------------------------

def ledger_append(event: dict) -> bool:
    """Append an event to the kernel's HBP evidence ledger. Returns whether
    the append succeeded; never raises."""
    cfg = get_binding_config("ledger")
    if cfg["mode"] == "off" or not is_kernel_available():
        return False
    try:
        _run_kernel(
            ["ledger", "append", "--json"],
            timeout=8.0,
            input_data=json.dumps(event),
        )
        return True
    except KernelBindingError as exc:
        logger.debug("kernel_binding.ledger: append failed (non-fatal): %s", exc)
        return False
