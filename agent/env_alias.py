"""Central ``SIMPLICIO_AGENT_*`` -> ``HERMES_*`` env alias reader (issue #117).

Today the only env var with a canonical/legacy alias pair is ``HOME``
(``SIMPLICIO_AGENT_HOME`` -> ``HERMES_HOME``, read ad hoc inside
``hermes_constants.get_hermes_home()``). Every call site that wants the same
"new name wins, old name still works" contract for a *different* var
currently has to hand-roll ``os.environ.get("SIMPLICIO_AGENT_X") or
os.environ.get("HERMES_X")`` — which is exactly the kind of duplicated,
easy-to-typo logic issue #117 asks to stop growing.

This module gives that pattern one home: ``env_get("X")`` resolves
``SIMPLICIO_AGENT_X`` first, then ``HERMES_X``, then a caller-supplied
default. The ``HERMES_*`` prefix is never removed here or anywhere else —
the Rust runtime reads 100+ ``HERMES_*`` vars as a cross-repo contract (see
``AGENTS.md``); aliasing only *adds* the canonical name, it never drops the
legacy one.

Scope note: issue #117's full plan also asks for a generated
``docs/ENV_VARS.md`` + ``agent/env_registry.py`` cataloguing all ~525
``HERMES_*`` vars, and for ~30 of them to be wired through this alias by
name. That catalog/wiring is intentionally **out of scope** for this change
(too large a diff to review safely in one PR) — this module is the
generic, tested primitive that catalog would eventually call into.
"""

from __future__ import annotations

import os

_CANONICAL_PREFIX = "SIMPLICIO_AGENT_"
_LEGACY_PREFIX = "HERMES_"


def canonical_env_name(suffix: str) -> str:
    """Return the canonical ``SIMPLICIO_AGENT_<suffix>`` env var name."""
    return f"{_CANONICAL_PREFIX}{suffix}"


def legacy_env_name(suffix: str) -> str:
    """Return the legacy ``HERMES_<suffix>`` env var name."""
    return f"{_LEGACY_PREFIX}{suffix}"


def env_get(suffix: str, default: str | None = None) -> str | None:
    """Resolve an aliased env var: ``SIMPLICIO_AGENT_<suffix>`` wins over
    ``HERMES_<suffix>``, which wins over *default*.

    ``suffix`` is the shared tail after either prefix, e.g. ``"HOME"`` for
    ``SIMPLICIO_AGENT_HOME``/``HERMES_HOME``, or ``"TOKEN_SAVINGS_LOG"`` for
    ``SIMPLICIO_AGENT_TOKEN_SAVINGS_LOG``/``HERMES_TOKEN_SAVINGS_LOG``.

    A value is only used if it is non-empty after stripping whitespace —
    an explicitly-set-but-blank env var (``HERMES_X=""``) is treated the
    same as unset, matching the existing behaviour of
    ``hermes_constants.get_hermes_home()``.
    """
    for name in (canonical_env_name(suffix), legacy_env_name(suffix)):
        val = os.environ.get(name, "")
        if val.strip():
            return val
    return default


def env_get_bool(suffix: str, default: bool = False) -> bool:
    """Boolean form of :func:`env_get`. Recognizes the usual truthy strings."""
    raw = env_get(suffix)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def which_env_set(suffix: str) -> str | None:
    """Return whichever of the two env var names is actually set (non-empty).

    Returns the canonical name if both are set (it takes precedence), the
    legacy name if only it is set, or ``None`` if neither is set. Useful for
    diagnostics/doctor output that must report *which* name is in play
    without leaking the value (see the no-secrets-in-logs rule in
    ``simplicio-dev-cli``'s ``CLAUDE.md``, mirrored here defensively even
    though this repo's own AGENTS.md doesn't require it verbatim).
    """
    canonical = canonical_env_name(suffix)
    if os.environ.get(canonical, "").strip():
        return canonical
    legacy = legacy_env_name(suffix)
    if os.environ.get(legacy, "").strip():
        return legacy
    return None
