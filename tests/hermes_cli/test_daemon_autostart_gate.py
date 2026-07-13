"""Tests for hermes_cli.main._should_autostart_daemon (issue #110).

Covers the CLI-side gate that decides whether an interactive invocation is
eligible to trigger warm-daemon auto-start. This module never spawns a
process itself — it only computes True/False; the actual spawn logic lives
in ``hermes_cli.daemon.maybe_autostart`` (see ``tests/hermes_cli/test_daemon.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_cli.main import _should_autostart_daemon


def _args(**overrides):
    base = {"command": None, "tui": False, "query": None}
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _interactive_tty(monkeypatch):
    """Default all tests to a real interactive terminal on both ends;
    individual tests override this to exercise the non-interactive path."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)


class TestShouldAutostartDaemon:
    def test_bare_invocation_is_eligible(self):
        assert _should_autostart_daemon(_args(command=None)) is True

    def test_chat_command_is_eligible(self):
        assert _should_autostart_daemon(_args(command="chat")) is True

    def test_rl_command_is_eligible(self):
        assert _should_autostart_daemon(_args(command="rl")) is True

    def test_tui_launch_is_eligible(self):
        assert _should_autostart_daemon(_args(command="chat", tui=True)) is True

    def test_unrelated_subcommand_is_not_eligible(self):
        assert _should_autostart_daemon(_args(command="cron")) is False

    def test_one_shot_query_flag_is_not_eligible(self):
        """``-q``/``--query`` invocations must never auto-start (issue #110
        scope: "nunca para invocações one-shot com -q/scripts/CI")."""
        assert _should_autostart_daemon(_args(command="chat", query="ping")) is False

    def test_non_tty_stdin_is_not_eligible(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert _should_autostart_daemon(_args(command="chat")) is False

    def test_non_tty_stdout_is_not_eligible(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert _should_autostart_daemon(_args(command="chat")) is False

    def test_piped_ci_invocation_is_not_eligible(self, monkeypatch):
        """Simulates a CI/script invocation: neither stdin nor stdout is a
        TTY, matching how CI runners actually invoke the CLI."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert _should_autostart_daemon(_args(command=None)) is False
