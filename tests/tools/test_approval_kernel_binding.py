"""Tests for the F2 (#20) kernel action-gate binding wired into
tools/approval.py::check_dangerous_command via _kernel_action_gate_precheck.

These tests exist specifically to prove two things the issue's acceptance
criteria call out:

1. Zero regression: with the binding degraded (no kernel, default 'auto'
   mode), `check_dangerous_command` behaves exactly as it did before #20.
2. Fail-closed: with `kernel_binding.action_gate.mode: required` and no
   kernel on PATH, a flagged-dangerous command is blocked with a clear
   message instead of silently falling through to the legacy approval flow.
"""

import os
from unittest.mock import patch as mock_patch

import pytest

import tools.approval as approval_module
import tools.kernel_binding as kernel_binding_module
from tools.approval import check_dangerous_command


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    approval_module._session_approved.clear()
    approval_module._pending.clear()
    approval_module._permanent_approved.clear()
    kernel_binding_module.reset_kernel_cache()
    for k in ("HERMES_INTERACTIVE", "HERMES_GATEWAY_SESSION", "HERMES_EXEC_ASK",
              "HERMES_YOLO_MODE", "HERMES_SESSION_KEY", "HERMES_KERNEL_BIN"):
        monkeypatch.delenv(k, raising=False)
    yield
    approval_module._session_approved.clear()
    approval_module._pending.clear()
    approval_module._permanent_approved.clear()
    kernel_binding_module.reset_kernel_cache()


class TestDefaultFailsClosedWithoutKernel:
    """ADR-0003: the agent always runs with the runtime. Default config +
    no kernel on PATH -> flagged-dangerous commands are blocked with a
    kernel message, before the legacy prompt ever runs."""

    def test_absent_kernel_blocks_by_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session")

        def _boom_if_called(*a, **k):
            raise AssertionError("legacy prompt must not run under default fail-closed")

        with mock_patch("hermes_cli.config.load_config", return_value={}), \
             mock_patch("shutil.which", return_value=None), \
             mock_patch("tools.runtime_manager.managed_bin_dir",
                        return_value=__import__("pathlib").Path("/nonexistent")):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=_boom_if_called,
            )
        assert result["approved"] is False
        assert "kernel" in result["message"].lower()


class TestConfigRelaxRestoresLegacyFlow:
    """`kernel_binding.action_gate.mode: auto` opts a machine back into the
    pre-ADR-0003 honest degradation -- legacy flow, byte for byte."""

    _RELAXED = {"kernel_binding": {"action_gate": {"mode": "auto"}}}

    def test_legacy_deny_flow_unaffected(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session")
        with mock_patch("hermes_cli.config.load_config", return_value=self._RELAXED), \
             mock_patch("shutil.which", return_value=None), \
             mock_patch("tools.runtime_manager.managed_bin_dir",
                        return_value=__import__("pathlib").Path("/nonexistent")):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=lambda *a, **k: "deny",
            )
        assert result["approved"] is False
        assert "BLOCKED" in result["message"]
        # The legacy message, not a kernel-gate message.
        assert "kernel" not in result["message"].lower()

    def test_legacy_approve_flow_unaffected(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session-2")
        with mock_patch("hermes_cli.config.load_config", return_value=self._RELAXED), \
             mock_patch("shutil.which", return_value=None), \
             mock_patch("tools.runtime_manager.managed_bin_dir",
                        return_value=__import__("pathlib").Path("/nonexistent")):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=lambda *a, **k: "session",
            )
        assert result["approved"] is True


class TestKernelDenyBlocksBeforeLegacyPrompt:
    def test_kernel_deny_short_circuits(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session-3")

        def _boom_if_called(*a, **k):
            raise AssertionError("legacy interactive prompt must not run when the kernel already denied")

        with mock_patch.object(
            kernel_binding_module, "evaluate_action_gate",
            return_value={"approved": False, "message": "BLOCKED by simplicio kernel action gate: too risky"},
        ):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=_boom_if_called,
            )
        assert result["approved"] is False
        assert "too risky" in result["message"]


class TestFailClosedRequiredMode:
    """AC: kernel absent + risky action + mode=required -> block, clear message."""

    def test_required_mode_blocks_without_prompting(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session-4")

        def _boom_if_called(*a, **k):
            raise AssertionError("legacy interactive prompt must not run in fail-closed required mode")

        cfg = {"kernel_binding": {"action_gate": {"mode": "required"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg), \
             mock_patch("shutil.which", return_value=None):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=_boom_if_called,
            )
        assert result["approved"] is False
        assert "required" in result["message"]
        assert "simplicio" in result["message"]


class TestPrecheckIsDefensive:
    """A bug in the binding must degrade to legacy behavior, never crash
    the safety-critical approval module."""

    def test_unexpected_exception_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_SESSION_KEY", "test-session-5")
        with mock_patch.object(
            kernel_binding_module, "evaluate_action_gate",
            side_effect=RuntimeError("unexpected bug in the binding"),
        ):
            result = check_dangerous_command(
                "rm -rf /tmp/stuff", "local", approval_callback=lambda *a, **k: "deny",
            )
        # Falls through to the legacy flow, which denies via the callback --
        # proves the module didn't crash and didn't silently auto-approve.
        assert result["approved"] is False
