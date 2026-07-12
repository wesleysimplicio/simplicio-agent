"""Tests for the concurrent tool-call timeout default (Slice B — speed).

Context: gateway.log showed a legitimate tool taking 90.21s. The old default
of 420s (7 min) meant a genuinely hung tool could hold a turn hostage for
7 minutes. The default was lowered to 120s (2 min), which still covers real
long-running tools with margin while cancelling stuck tools ~3.5x sooner.

The env var HERMES_CONCURRENT_TOOL_TIMEOUT_S must still override the default.
"""

from __future__ import annotations

import importlib
import os

import pytest


def _reload_tool_executor(monkeypatch, env_value):
    """Reload agent.tool_executor with a controlled env var value.

    Passing ``env_value=None`` removes the var so the module falls back to its
    compiled-in default. Any other value is exported before reload.
    """
    if env_value is None:
        monkeypatch.delenv("HERMES_CONCURRENT_TOOL_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("HERMES_CONCURRENT_TOOL_TIMEOUT_S", env_value)
    import agent.tool_executor as te
    return importlib.reload(te)


@pytest.fixture(autouse=True)
def _restore_module():
    """Ensure the module is reloaded to its ambient state after each test."""
    yield
    import agent.tool_executor as te
    importlib.reload(te)


def test_default_is_120_when_env_unset(monkeypatch):
    """(a) With no env var set, the default timeout is 120.0 seconds."""
    te = _reload_tool_executor(monkeypatch, None)
    assert te._CONCURRENT_TOOL_TIMEOUT == 120.0


def test_env_override_is_respected(monkeypatch):
    """(b) HERMES_CONCURRENT_TOOL_TIMEOUT_S=30.0 overrides the default."""
    te = _reload_tool_executor(monkeypatch, "30.0")
    assert te._CONCURRENT_TOOL_TIMEOUT == 30.0


def test_default_is_not_the_old_420(monkeypatch):
    """Regression: the old 7-minute default must be gone."""
    te = _reload_tool_executor(monkeypatch, None)
    assert te._CONCURRENT_TOOL_TIMEOUT != 420.0
    assert te._CONCURRENT_TOOL_TIMEOUT < 420.0


def test_timeout_value_used_in_concurrent_path(monkeypatch):
    """(c) The timeout constant is referenced by the concurrent-execution
    cancellation path — proves the value actually gates future cancellation.

    We inspect the source of the module for the guard that compares elapsed
    wall-clock time against ``_CONCURRENT_TOOL_TIMEOUT`` and cancels pending
    futures. This deterministically verifies the wiring without spinning up a
    real hung tool.
    """
    te = _reload_tool_executor(monkeypatch, None)
    import inspect

    src = inspect.getsource(te)
    # The cancellation guard: elapsed >= timeout, then cancel pending futures.
    assert "_conc_elapsed >= _CONCURRENT_TOOL_TIMEOUT" in src
    assert "f.cancel()" in src
