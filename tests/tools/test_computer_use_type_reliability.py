"""Tests for the `type` action's background -> foreground escalation.

Background delivery (PostMessage, cua-driver's default) never steals focus,
but can only self-verify the typed text landed when the target control
exposes UI Automation's ValuePattern. When it can't, cua-driver still
reports `ok=True` ("delivered, not verified") — a silent maybe-failure.
`tools.computer_use.tool._type_with_escalation` closes that gap by retrying
once with `delivery_mode="foreground"` (SendInput) exactly when the first
attempt is ambiguous, and never otherwise. See tools/computer_use/tool.py
and tools/computer_use/cua_backend.py's `CuaDriverBackend.type_text`.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from tools.computer_use.backend import ActionResult, CaptureResult, ComputerUseBackend


@pytest.fixture(autouse=True)
def _reset_backend():
    """Tear down the cached backend between tests (mirrors test_computer_use.py)."""
    from tools.computer_use.tool import reset_backend_for_tests
    reset_backend_for_tests()
    yield
    reset_backend_for_tests()


VERIFIED_MSG = "Typed 5 char(s) on pid 123 via PostMessage (30ms delay; verified via UIA read-back)."
UNVERIFIED_MSG = (
    "Typed 5 char(s) on pid 123 via PostMessage (30ms delay; delivered, not verified — "
    "could not read the focused field back, e.g. the target isn't foreground or exposes "
    "no ValuePattern). If it didn't land, retry with delivery_mode:\"foreground\"."
)
FOREGROUND_OK_MSG = "Typed 5 char(s) on pid 123 via SendInput (delivery_mode:foreground)."


class _FakeBackend(ComputerUseBackend):
    """Test double whose `type_text` return value is fully controllable.

    `responses` is a queue of ActionResult (or an Exception instance/class to
    raise) consumed one per call, in order. Everything else is a minimal
    stub — only `type_text` and call bookkeeping matter for these tests.
    """

    def __init__(self, responses: List[Any]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def start(self) -> None: pass
    def stop(self) -> None: pass
    def is_available(self) -> bool: return True

    def capture(self, mode: str = "som", app: Optional[str] = None) -> CaptureResult:
        return CaptureResult(mode=mode, width=100, height=100, png_b64=None, elements=[])

    def click(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="click")

    def drag(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="drag")

    def scroll(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="scroll")

    def type_text(self, text: str, *, delivery_mode: str = "background") -> ActionResult:
        self.calls.append({"text": text, "delivery_mode": delivery_mode})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("fake error")
        return item

    def key(self, keys: str) -> ActionResult:
        return ActionResult(ok=True, action="key")

    def list_apps(self) -> List[Dict[str, Any]]:
        return []

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        return ActionResult(ok=True, action="focus_app")

    def set_value(self, value: str, element: Optional[int] = None) -> ActionResult:
        return ActionResult(ok=True, action="set_value")


class _NoDeliveryModeBackend(ComputerUseBackend):
    """Old-style backend whose `type_text` has no `delivery_mode` kwarg at
    all — simulates a pre-escalation backend (or _NoopBackend's shape)."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def start(self) -> None: pass
    def stop(self) -> None: pass
    def is_available(self) -> bool: return True

    def capture(self, mode: str = "som", app: Optional[str] = None) -> CaptureResult:
        return CaptureResult(mode=mode, width=100, height=100, png_b64=None, elements=[])

    def click(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="click")

    def drag(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="drag")

    def scroll(self, **kw) -> ActionResult:
        return ActionResult(ok=True, action="scroll")

    def type_text(self, text: str) -> ActionResult:  # note: no delivery_mode param
        self.calls.append(text)
        return ActionResult(ok=True, action="type", message=UNVERIFIED_MSG)

    def key(self, keys: str) -> ActionResult:
        return ActionResult(ok=True, action="key")

    def list_apps(self) -> List[Dict[str, Any]]:
        return []

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        return ActionResult(ok=True, action="focus_app")

    def set_value(self, value: str, element: Optional[int] = None) -> ActionResult:
        return ActionResult(ok=True, action="set_value")


def _install_backend(backend: ComputerUseBackend):
    from tools.computer_use import tool as cu_tool
    cu_tool.reset_backend_for_tests()
    cu_tool._backend = backend


class TestTypeEscalation:
    def test_verified_background_is_a_single_call(self):
        """Confirmed-fast-path: no escalation, no added latency."""
        from tools.computer_use import tool as cu_tool

        backend = _FakeBackend([ActionResult(ok=True, action="type", message=VERIFIED_MSG)])
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 1
        assert backend.calls[0]["delivery_mode"] == "background"
        assert parsed["ok"] is True
        assert VERIFIED_MSG in parsed["message"]

    def test_unverified_background_escalates_and_succeeds(self):
        """Ambiguous background result -> one foreground retry -> success."""
        from tools.computer_use import tool as cu_tool

        backend = _FakeBackend([
            ActionResult(ok=True, action="type", message=UNVERIFIED_MSG),
            ActionResult(ok=True, action="type", message=FOREGROUND_OK_MSG),
        ])
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 2
        assert backend.calls[0]["delivery_mode"] == "background"
        assert backend.calls[1]["delivery_mode"] == "foreground"
        assert parsed["ok"] is True
        assert "escalated to foreground" in parsed["message"]
        assert parsed.get("meta", {}).get("delivery_escalated") is True
        assert parsed.get("meta", {}).get("delivery_escalation_ok") is True

    def test_unverified_background_then_failed_foreground_still_ok(self):
        """Foreground retry also fails -> report original (ok=True) background
        result, not a hard failure. A failed escalation attempt must never
        make a plausibly-successful action look like it failed."""
        from tools.computer_use import tool as cu_tool

        backend = _FakeBackend([
            ActionResult(ok=True, action="type", message=UNVERIFIED_MSG),
            ActionResult(ok=False, action="type", message="No active window"),
        ])
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 2
        assert parsed["ok"] is True
        assert "foreground escalation also failed" in parsed["message"]
        assert parsed.get("meta", {}).get("delivery_escalated") is True
        assert parsed.get("meta", {}).get("delivery_escalation_ok") is False

    def test_unverified_background_then_foreground_raises_still_ok(self):
        """Foreground retry raises (e.g. driver RPC error) -> still report the
        original ok=True background result, with a note."""
        from tools.computer_use import tool as cu_tool

        backend = _FakeBackend([
            ActionResult(ok=True, action="type", message=UNVERIFIED_MSG),
            RuntimeError("cua-driver RPC timeout"),
        ])
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 2
        assert parsed["ok"] is True
        assert "foreground escalation errored" in parsed["message"]

    def test_hard_failure_does_not_escalate(self):
        """ok=False is a real failure (e.g. no active window) — no retry."""
        from tools.computer_use import tool as cu_tool

        backend = _FakeBackend([
            ActionResult(ok=False, action="type_text", message="No active window — call capture() first."),
        ])
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 1
        assert parsed["ok"] is False

    def test_backend_without_delivery_mode_support_degrades_to_single_call(self):
        """A backend whose type_text has no delivery_mode kwarg at all must
        not crash the `type` action — escalation degrades to a no-op."""
        from tools.computer_use import tool as cu_tool

        backend = _NoDeliveryModeBackend()
        _install_backend(backend)

        out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert len(backend.calls) == 1
        assert parsed["ok"] is True

    def test_real_noop_backend_degrades_to_single_call(self):
        """Same guarantee against the actual _NoopBackend used by the rest of
        the test suite for hermetic (no cua-driver) testing."""
        from tools.computer_use import tool as cu_tool

        cu_tool.reset_backend_for_tests()
        with patch.dict(os.environ, {"HERMES_COMPUTER_USE_BACKEND": "noop"}, clear=False):
            backend = cu_tool._get_backend()
            out = cu_tool.handle_computer_use({"action": "type", "text": "hello"})

        parsed = json.loads(out)
        type_calls = [c for c in backend.calls if c[0] == "type"]
        assert len(type_calls) == 1
        assert parsed["ok"] is True
