"""Tests for issue #190 — file/dir/import move-with-shim (no break).

The canonical public entry ``simplicio_agent.entry.main`` must forward to the
real CLI implementation, and ``python -m simplicio_agent`` must resolve to the
same entry. The legacy ``hermes_cli.main`` path must remain importable so
existing compat aliases keep working.
"""

from __future__ import annotations

import importlib

import hermes_cli.main as legacy_main
import simplicio_agent.entry as entry


def test_canonical_entry_forwards_to_real_cli():
    # The public entry must delegate to the actual CLI implementation.
    assert entry.main is legacy_main.main


def test_python_minus_m_module_resolves_entry():
    mod = importlib.import_module("simplicio_agent.__main__")
    assert mod.main is entry.main
    assert mod.main is legacy_main.main


def test_legacy_cli_module_still_importable():
    # Move-with-shim must not break the legacy internal entry point that the
    # deprecated hermes* console scripts still reference.
    assert callable(legacy_main.main)
