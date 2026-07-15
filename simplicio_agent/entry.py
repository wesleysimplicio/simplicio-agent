"""Canonical console entry point for Simplicio Agent.

This is the public, import-safe entry surface. ``simplicio_agent.entry.main``
re-exports the real CLI implementation (currently ``hermes_cli.main.main``) so
the public namespace owns the entry while the underlying implementation stays
where it is during the incremental #186 migration. Legacy entry points
(``hermes_cli.main:main`` via the ``hermes``/``hermes-agent`` compat aliases)
continue to work unchanged; this module is the canonical path.
"""

from __future__ import annotations

from hermes_cli.main import main

__all__ = ["main"]
