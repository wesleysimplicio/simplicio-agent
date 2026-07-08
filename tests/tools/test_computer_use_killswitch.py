"""Tests for the computer_use runtime killswitch and its MCP safety gate.

Covers:
  - ``tools.computer_use.killswitch`` — the process-level pause flag itself.
  - ``tools.computer_use.tool.handle_computer_use`` — killswitch gating
    (paused blocks destructive actions, safe actions stay reachable,
    unpause restores destructive actions, the cached backend is torn down
    on pause, and the pre-existing hard blocklists are unaffected).
  - ``mcp_serve._computer_use_mcp_refusal`` — the FastMCP safe-actions-only
    gate (``SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL``) plus killswitch
    enforcement. This is pure Python with no ``mcp`` import at decision
    time, so it's testable even where the optional ``mcp`` extra isn't
    installed.
  - ``mcp_serve._computer_use_result_to_mcp_content`` — mapping
    ``handle_computer_use``'s text/multimodal return shape onto MCP content
    blocks. Guarded behind an ``mcp`` import-skip since it needs real
    ``mcp.types`` classes.
  - ``hermes_cli.web_server``'s ``GET``/``PUT /api/tools/computer-use/pause``
    routes. Guarded behind a ``fastapi`` import-skip.

Forces ``HERMES_COMPUTER_USE_BACKEND=noop`` like test_computer_use.py so no
real cua-driver process is ever spawned.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_killswitch_and_backend():
    """Reset the killswitch + cached backend around each test, and force
    the noop backend so no real cua-driver process is ever spawned."""
    from tools.computer_use import killswitch
    from tools.computer_use.tool import reset_backend_for_tests

    killswitch.reset_for_tests()
    reset_backend_for_tests()
    with patch.dict(os.environ, {"HERMES_COMPUTER_USE_BACKEND": "noop"}, clear=False):
        yield
    killswitch.reset_for_tests()
    reset_backend_for_tests()


@pytest.fixture
def noop_backend():
    """Return the active noop backend instance so tests can inspect calls."""
    from tools.computer_use.tool import _get_backend
    return _get_backend()


# ---------------------------------------------------------------------------
# tools.computer_use.killswitch — the module itself
# ---------------------------------------------------------------------------

class TestKillswitchModule:
    def test_defaults_to_unpaused_with_no_reason(self):
        from tools.computer_use import killswitch

        assert killswitch.is_paused() is False
        assert killswitch.get_reason() is None

    def test_set_paused_true_then_false(self):
        from tools.computer_use import killswitch

        killswitch.set_paused(True)
        assert killswitch.is_paused() is True
        killswitch.set_paused(False)
        assert killswitch.is_paused() is False

    def test_reason_is_recorded_and_cleared_on_unpause(self):
        from tools.computer_use import killswitch

        killswitch.set_paused(True, reason="user clicked pause")
        assert killswitch.get_reason() == "user clicked pause"
        killswitch.set_paused(False)
        assert killswitch.get_reason() is None

    def test_set_paused_coerces_non_bool_truthy_values(self):
        from tools.computer_use import killswitch

        killswitch.set_paused(1)  # type: ignore[arg-type]
        assert killswitch.is_paused() is True
        assert isinstance(killswitch.is_paused(), bool)


# ---------------------------------------------------------------------------
# handle_computer_use — killswitch gating
# ---------------------------------------------------------------------------

class TestHandleComputerUseKillswitch:
    def test_click_refused_while_paused(self, noop_backend):
        from tools.computer_use import killswitch
        from tools.computer_use.tool import handle_computer_use

        killswitch.set_paused(True)
        out = handle_computer_use({"action": "click", "element": 1})
        parsed = json.loads(out)

        assert parsed.get("paused") is True
        assert "killswitch" in parsed["error"].lower()
        assert not any(c[0] == "click" for c in noop_backend.calls)

    def test_type_refused_while_paused(self, noop_backend):
        from tools.computer_use import killswitch
        from tools.computer_use.tool import handle_computer_use

        killswitch.set_paused(True)
        out = handle_computer_use({"action": "type", "text": "hello"})
        parsed = json.loads(out)

        assert parsed.get("paused") is True
        assert not any(c[0] == "type" for c in noop_backend.calls)

    def test_capture_still_works_while_paused(self):
        from tools.computer_use import killswitch
        from tools.computer_use.tool import handle_computer_use

        killswitch.set_paused(True)
        out = handle_computer_use({"action": "capture", "mode": "ax"})
        parsed = json.loads(out)

        assert "error" not in parsed
        assert parsed["mode"] == "ax"

    def test_wait_and_list_apps_still_work_while_paused(self):
        from tools.computer_use import killswitch
        from tools.computer_use.tool import handle_computer_use

        killswitch.set_paused(True)

        wait_out = json.loads(handle_computer_use({"action": "wait", "seconds": 0.01}))
        assert wait_out["ok"] is True

        apps_out = json.loads(handle_computer_use({"action": "list_apps"}))
        assert "apps" in apps_out

    def test_pausing_tears_down_the_cached_backend(self, noop_backend):
        """A paused destructive action must release the backend, not just
        refuse it — otherwise a live cua-driver subprocess sits idle,
        immediately drivable the instant the killswitch flips back off."""
        from tools.computer_use import killswitch, tool as cu_tool

        assert cu_tool._backend is noop_backend  # sanity: backend is cached
        killswitch.set_paused(True)
        cu_tool.handle_computer_use({"action": "click", "element": 1})

        assert cu_tool._backend is None
        assert noop_backend._started is False

    def test_unpause_restores_destructive_actions(self, noop_backend):
        from tools.computer_use import killswitch
        from tools.computer_use.tool import _get_backend, handle_computer_use

        killswitch.set_paused(True)
        blocked = json.loads(handle_computer_use({"action": "click", "element": 1}))
        assert blocked.get("paused") is True

        killswitch.set_paused(False)
        out = handle_computer_use({"action": "click", "element": 1})
        parsed = json.loads(out)

        assert "error" not in parsed
        assert parsed["ok"] is True
        # The pause teardown drops the pre-pause backend, so a fresh one is
        # lazily created on the next call — assert against the CURRENT
        # instance rather than the one the fixture captured before pausing.
        current_backend = _get_backend()
        assert any(c[0] == "click" for c in current_backend.calls)

    def test_blocked_key_combo_enforced_even_when_paused(self):
        """Killswitch is additive, not a replacement for the pre-existing
        hard blocklists — those must keep returning their own specific
        error regardless of pause state."""
        from tools.computer_use import killswitch
        from tools.computer_use.tool import handle_computer_use

        killswitch.set_paused(True)
        out = handle_computer_use({"action": "key", "keys": "cmd+shift+q"})
        parsed = json.loads(out)
        assert "blocked key combo" in parsed["error"]

    def test_blocked_type_pattern_enforced_even_when_unpaused(self):
        from tools.computer_use.tool import handle_computer_use

        out = handle_computer_use({"action": "type", "text": "sudo rm -rf /etc"})
        parsed = json.loads(out)
        assert "blocked pattern" in parsed["error"]


# ---------------------------------------------------------------------------
# mcp_serve._computer_use_mcp_refusal — safe-actions-only gate for MCP
# ---------------------------------------------------------------------------

class TestMcpComputerUseSafetyGate:
    """Pure decision logic, no `mcp` package import required."""

    def test_safe_actions_always_allowed(self, monkeypatch):
        import mcp_serve

        monkeypatch.delenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", raising=False)
        for action in ("capture", "wait", "list_apps"):
            assert mcp_serve._computer_use_mcp_refusal(action) is None

    def test_destructive_action_refused_without_env_opt_in(self, monkeypatch):
        import mcp_serve

        monkeypatch.delenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", raising=False)
        refusal = mcp_serve._computer_use_mcp_refusal("click")

        assert refusal is not None
        assert "click" in refusal
        assert "SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL" in refusal

    def test_destructive_action_allowed_with_env_opt_in(self, monkeypatch):
        import mcp_serve

        monkeypatch.setenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", "1")
        assert mcp_serve._computer_use_mcp_refusal("click") is None

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "off", ""])
    def test_falsy_env_values_still_refuse(self, monkeypatch, falsy):
        import mcp_serve

        monkeypatch.setenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", falsy)
        assert mcp_serve._computer_use_mcp_refusal("type") is not None

    def test_killswitch_still_refuses_even_with_env_opt_in(self, monkeypatch):
        import mcp_serve
        from tools.computer_use import killswitch

        monkeypatch.setenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", "1")
        killswitch.set_paused(True)
        refusal = mcp_serve._computer_use_mcp_refusal("click")

        assert refusal is not None
        assert "paused" in refusal.lower() or "killswitch" in refusal.lower()

    def test_safe_action_allowed_even_when_paused_and_env_unset(self, monkeypatch):
        """Safe actions bypass both the env gate and the killswitch."""
        import mcp_serve
        from tools.computer_use import killswitch

        monkeypatch.delenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", raising=False)
        killswitch.set_paused(True)
        assert mcp_serve._computer_use_mcp_refusal("capture") is None

    def test_action_normalization_is_case_and_whitespace_insensitive(self, monkeypatch):
        import mcp_serve

        monkeypatch.delenv("SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL", raising=False)
        assert mcp_serve._computer_use_mcp_refusal("  Capture  ") is None


# ---------------------------------------------------------------------------
# mcp_serve._computer_use_result_to_mcp_content — text/image content mapping
# ---------------------------------------------------------------------------

class TestMcpResultContentMapping:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp", reason="mcp extra not installed")

    def test_text_only_string_result_becomes_single_text_block(self):
        import mcp_serve
        from mcp.types import TextContent

        blocks = mcp_serve._computer_use_result_to_mcp_content(json.dumps({"ok": True}))

        assert len(blocks) == 1
        assert isinstance(blocks[0], TextContent)
        assert json.loads(blocks[0].text) == {"ok": True}

    def test_multimodal_envelope_becomes_text_and_image_blocks(self):
        import mcp_serve
        from mcp.types import ImageContent, TextContent

        fake_png_b64 = "iVBORw0KGgo="
        envelope = {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": "1 element"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{fake_png_b64}"}},
            ],
            "text_summary": "1 element",
        }

        blocks = mcp_serve._computer_use_result_to_mcp_content(envelope)

        text_blocks = [b for b in blocks if isinstance(b, TextContent)]
        image_blocks = [b for b in blocks if isinstance(b, ImageContent)]
        assert any(b.text == "1 element" for b in text_blocks)
        assert len(image_blocks) == 1
        assert image_blocks[0].data == fake_png_b64
        assert image_blocks[0].mimeType == "image/png"

    def test_multimodal_envelope_with_no_content_falls_back_to_summary(self):
        import mcp_serve
        from mcp.types import TextContent

        envelope = {"_multimodal": True, "content": [], "text_summary": "fallback"}
        blocks = mcp_serve._computer_use_result_to_mcp_content(envelope)

        assert len(blocks) == 1
        assert isinstance(blocks[0], TextContent)
        assert blocks[0].text == "fallback"


# ---------------------------------------------------------------------------
# REST endpoints — GET/PUT /api/tools/computer-use/pause
# ---------------------------------------------------------------------------

class TestComputerUsePauseRestEndpoints:
    @pytest.fixture(autouse=True)
    def _require_fastapi(self):
        pytest.importorskip("fastapi", reason="dashboard extra not installed")

    @pytest.mark.asyncio
    async def test_get_reports_default_unpaused(self):
        from hermes_cli import web_server

        result = await web_server.get_computer_use_pause()
        assert result == {"paused": False}

    @pytest.mark.asyncio
    async def test_put_pauses_and_get_reflects_it(self):
        from hermes_cli import web_server
        from tools.computer_use import killswitch

        result = await web_server.set_computer_use_pause(
            web_server.ComputerUsePause(paused=True)
        )
        assert result == {"ok": True, "paused": True}
        assert killswitch.is_paused() is True

        get_result = await web_server.get_computer_use_pause()
        assert get_result == {"paused": True}

    @pytest.mark.asyncio
    async def test_put_unpauses(self):
        from hermes_cli import web_server
        from tools.computer_use import killswitch

        killswitch.set_paused(True)
        result = await web_server.set_computer_use_pause(
            web_server.ComputerUsePause(paused=False)
        )
        assert result == {"ok": True, "paused": False}
        assert killswitch.is_paused() is False
