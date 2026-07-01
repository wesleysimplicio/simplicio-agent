"""Tests for user-defined quick commands that bypass the agent loop."""
import os
import subprocess
from unittest.mock import MagicMock, patch
from rich.text import Text
import pytest


# ── CLI tests ──────────────────────────────────────────────────────────────

class TestCLIQuickCommands:
    """Test quick command dispatch in HermesCLI.process_command."""

    @staticmethod
    def _printed_plain(call_arg):
        if isinstance(call_arg, Text):
            return call_arg.plain
        return str(call_arg)

    def _make_cli(self, quick_commands):
        from cli import HermesCLI
        cli = HermesCLI.__new__(HermesCLI)
        cli.config = {"quick_commands": quick_commands}
        cli.console = MagicMock()
        cli.agent = None
        cli.conversation_history = []
        # session_id is accessed by the fallback skill/fuzzy-match path in
        # process_command; without it, tests that exercise `/alias args`
        # can trip an AttributeError when cross-test state leaks a skill
        # command matching the alias target.
        cli.session_id = "test-session"
        return cli

    def test_exec_command_runs_and_prints_output(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        result = cli.process_command("/dn")
        assert result is True
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "daily-note"

    def test_exec_command_uses_chat_console_when_tui_is_live(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        cli._app = object()
        live_console = MagicMock()

        with patch("cli.ChatConsole", return_value=live_console):
            result = cli.process_command("/dn")

        assert result is True
        live_console.print.assert_called_once()
        printed = self._printed_plain(live_console.print.call_args[0][0])
        assert printed == "daily-note"
        cli.console.print.assert_not_called()

    def test_exec_command_stderr_shown_on_no_stdout(self):
        cli = self._make_cli({"err": {"type": "exec", "command": "echo error >&2"}})
        result = cli.process_command("/err")
        assert result is True
        # stderr fallback — should print something
        cli.console.print.assert_called_once()

    def test_exec_command_no_output_shows_fallback(self):
        cli = self._make_cli({"empty": {"type": "exec", "command": "true"}})
        cli.process_command("/empty")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no output" in args.lower()

    def test_alias_command_routes_to_target(self):
        """Alias quick commands rewrite to the target command."""
        cli = self._make_cli({"shortcut": {"type": "alias", "target": "/help"}})
        with patch.object(cli, "process_command", wraps=cli.process_command) as spy:
            cli.process_command("/shortcut")
            # Should recursively call process_command with /help
            spy.assert_any_call("/help")

    def test_alias_command_passes_args(self):
        """Alias quick commands forward user arguments to the target."""
        cli = self._make_cli({"sc": {"type": "alias", "target": "/context"}})
        with patch.object(cli, "process_command", wraps=cli.process_command) as spy:
            cli.process_command("/sc some args")
            spy.assert_any_call("/context some args")

    def test_alias_no_target_shows_error(self):
        cli = self._make_cli({"broken": {"type": "alias", "target": ""}})
        cli.process_command("/broken")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no target defined" in args.lower()

    def test_unsupported_type_shows_error(self):
        cli = self._make_cli({"bad": {"type": "prompt", "command": "echo hi"}})
        cli.process_command("/bad")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "unsupported type" in args.lower()

    def test_missing_command_field_shows_error(self):
        cli = self._make_cli({"oops": {"type": "exec"}})
        cli.process_command("/oops")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no command defined" in args.lower()

    def test_quick_command_takes_priority_over_skill_commands(self):
        """Quick commands must be checked before skill slash commands."""
        cli = self._make_cli({"mygif": {"type": "exec", "command": "echo overridden"}})
        with patch("cli._skill_commands", {"/mygif": {"name": "gif-search"}}):
            cli.process_command("/mygif")
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "overridden"

    def test_unknown_command_still_shows_error(self):
        cli = self._make_cli({})
        with patch("cli._cprint") as mock_cprint:
            cli.process_command("/nonexistent")
            mock_cprint.assert_called()
            printed = " ".join(str(c) for c in mock_cprint.call_args_list)
            assert "unknown command" in printed.lower()

    def test_timeout_shows_error(self):
        cli = self._make_cli({"slow": {"type": "exec", "command": "sleep 100"}})
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)):
            cli.process_command("/slow")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "timed out" in args.lower()


# ── Gateway tests ──────────────────────────────────────────────────────────

class TestGatewayQuickCommands:
    """Test quick command dispatch in GatewayRunner._handle_message."""

    def _make_event(self, command, args=""):
        event = MagicMock()
        event.get_command.return_value = command
        event.get_command_args.return_value = args
        event.text = f"/{command} {args}".strip()
        event.source = MagicMock()
        event.source.user_id = "test_user"
        event.source.user_name = "Test User"
        event.source.platform.value = "telegram"
        event.source.chat_type = "dm"
        event.source.chat_id = "123"
        return event

    @pytest.mark.asyncio
    async def test_exec_command_returns_output(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"limits": {"type": "exec", "command": "echo ok"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_exec_command_does_not_leak_credentials(self):
        """Quick command exec must sanitize env — API keys must not appear in output."""
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"leak": {"type": "exec", "command": "env"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("leak")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret-12345"}):
            result = await runner._handle_message(event)

        assert "sk-or-secret-12345" not in result, \
            "Quick command leaked OPENROUTER_API_KEY — exec runs without env sanitization"

    @pytest.mark.asyncio
    async def test_exec_command_output_is_redacted(self, monkeypatch):
        """Quick command output must redact sensitive patterns before returning."""
        from gateway.run import GatewayRunner

        # Ensure redaction is active regardless of host HERMES_REDACT_SECRETS state
        # or test ordering
        monkeypatch.setattr("agent.redact._REDACT_ENABLED", True)

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"token": {"type": "exec", "command": "echo sk-ant-api03-supersecretkey1234567890"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("token")
        result = await runner._handle_message(event)

        assert "supersecretkey1234567890" not in result, \
            "Quick command output not redacted — raw API key returned to user"

    @pytest.mark.asyncio
    async def test_unsupported_type_returns_error(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"bad": {"type": "prompt", "command": "echo hi"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("bad")
        result = await runner._handle_message(event)
        assert result is not None
        assert "unsupported type" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        from gateway.run import GatewayRunner
        import asyncio
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"slow": {"type": "exec", "command": "sleep 100"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("slow")
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await runner._handle_message(event)
        assert result is not None
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_gateway_config_object_supports_quick_commands(self):
        from gateway.config import GatewayConfig
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = GatewayConfig(
            quick_commands={"limits": {"type": "exec", "command": "echo ok"}}
        )
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"


# ── Deterministic router fast-path tests ────────────────────────────────────

class TestGatewayDeterministicRouterFastPath:
    """Test the no-LLM deterministic router wired into GatewayRunner._handle_message.

    The router only runs when ``event.get_command()`` is ``None`` — i.e. the
    input is NOT a slash command — so it can never shadow /help, /whoami,
    /version, quick_commands, plugin commands, or skill commands (all of
    which require a leading slash and are dispatched earlier in
    ``_handle_message``).
    """

    def _make_bare_event(self, text):
        """A plain-text (non-slash) inbound message, as real chat input looks."""
        event = MagicMock()
        event.get_command.return_value = None
        event.get_command_args.return_value = text
        event.text = text
        event.internal = False
        event.source = MagicMock()
        event.source.user_id = "test_user"
        event.source.user_name = "Test User"
        event.source.platform.value = "telegram"
        event.source.chat_type = "dm"
        event.source.chat_id = "123"
        return event

    def _make_runner(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)
        return runner

    @pytest.mark.asyncio
    async def test_trivial_ping_answers_without_reaching_agent(self):
        """A bare 'ping' is answered instantly by the deterministic router —
        the agent/LLM turn (guarded by _is_telegram_topic_root_lobby, the
        first async call after the router fast path) must never be reached.
        """
        runner = self._make_runner()
        runner._is_telegram_topic_root_lobby = MagicMock(
            side_effect=AssertionError("LLM/agent path reached for a trivial router hit")
        )

        event = self._make_bare_event("ping")
        result = await runner._handle_message(event)

        assert result == "pong"
        runner._is_telegram_topic_root_lobby.assert_not_called()

    @pytest.mark.asyncio
    async def test_conversational_message_falls_through_to_existing_path_unchanged(self):
        """A normal conversational message is not a router match, so it must
        flow through to the existing (pre-existing, unmodified) code path —
        proven here by observing that the next real step after the router
        check (_is_telegram_topic_root_lobby) is reached.
        """
        runner = self._make_runner()
        runner._is_telegram_topic_root_lobby = MagicMock(
            side_effect=AssertionError("reached-existing-path")
        )

        async def _to_thread_stub(fn, *args, **kwargs):
            # asyncio.to_thread(self._is_telegram_topic_root_lobby, source)
            # Call the mock synchronously here to surface its side_effect
            # as proof execution reached this pre-existing gate.
            return fn(*args, **kwargs)

        with patch("asyncio.to_thread", side_effect=_to_thread_stub):
            with pytest.raises(AssertionError, match="reached-existing-path"):
                await runner._handle_message(
                    self._make_bare_event("Can you help me plan my trip to Lisbon next week?")
                )

    @pytest.mark.asyncio
    async def test_slash_ping_does_not_collide_with_router(self):
        """/ping (a slash command) must NOT be intercepted by the router —
        get_command() returns 'ping' (truthy), so the `command is None`
        guard skips the router entirely and the existing unknown-command
        handling for slash input applies instead.
        """
        runner = self._make_runner()

        event = MagicMock()
        event.get_command.return_value = "ping"
        event.get_command_args.return_value = ""
        event.text = "/ping"
        event.internal = False
        event.source = MagicMock()
        event.source.user_id = "test_user"
        event.source.user_name = "Test User"
        event.source.platform.value = "telegram"
        event.source.chat_type = "dm"
        event.source.chat_id = "123"

        result = await runner._handle_message(event)

        assert result != "pong"
        assert "unknown command" in (result or "").lower()
