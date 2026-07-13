"""Tests for agent.env_alias.env_get() — SIMPLICIO_AGENT_X -> HERMES_X (#117)."""

from __future__ import annotations

from agent.env_alias import (
    canonical_env_name,
    env_get,
    env_get_bool,
    legacy_env_name,
    which_env_set,
)


class TestEnvGet:
    def test_neither_set_returns_default(self, monkeypatch):
        monkeypatch.delenv("SIMPLICIO_AGENT_FOO", raising=False)
        monkeypatch.delenv("HERMES_FOO", raising=False)
        assert env_get("FOO") is None
        assert env_get("FOO", "fallback") == "fallback"

    def test_legacy_only_is_used(self, monkeypatch):
        monkeypatch.delenv("SIMPLICIO_AGENT_FOO", raising=False)
        monkeypatch.setenv("HERMES_FOO", "legacy-value")
        assert env_get("FOO") == "legacy-value"

    def test_canonical_only_is_used(self, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "canonical-value")
        monkeypatch.delenv("HERMES_FOO", raising=False)
        assert env_get("FOO") == "canonical-value"

    def test_canonical_wins_when_both_set(self, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "canonical-value")
        monkeypatch.setenv("HERMES_FOO", "legacy-value")
        assert env_get("FOO") == "canonical-value"

    def test_blank_value_treated_as_unset(self, monkeypatch):
        """An explicitly blank SIMPLICIO_AGENT_X must not shadow a real HERMES_X."""
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "   ")
        monkeypatch.setenv("HERMES_FOO", "legacy-value")
        assert env_get("FOO") == "legacy-value"

    def test_both_blank_returns_default(self, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "")
        monkeypatch.setenv("HERMES_FOO", "")
        assert env_get("FOO", "d") == "d"


class TestEnvGetBool:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SIMPLICIO_AGENT_FLAG", raising=False)
        monkeypatch.delenv("HERMES_FLAG", raising=False)
        assert env_get_bool("FLAG") is False
        assert env_get_bool("FLAG", default=True) is True

    def test_truthy_strings(self, monkeypatch):
        for val in ("1", "true", "True", "yes", "on"):
            monkeypatch.setenv("HERMES_FLAG", val)
            assert env_get_bool("FLAG") is True

    def test_falsy_strings(self, monkeypatch):
        for val in ("0", "false", "no", "off", "nonsense"):
            monkeypatch.setenv("HERMES_FLAG", val)
            assert env_get_bool("FLAG") is False


class TestWhichEnvSet:
    def test_neither_set(self, monkeypatch):
        monkeypatch.delenv("SIMPLICIO_AGENT_FOO", raising=False)
        monkeypatch.delenv("HERMES_FOO", raising=False)
        assert which_env_set("FOO") is None

    def test_legacy_set(self, monkeypatch):
        monkeypatch.delenv("SIMPLICIO_AGENT_FOO", raising=False)
        monkeypatch.setenv("HERMES_FOO", "x")
        assert which_env_set("FOO") == "HERMES_FOO"

    def test_canonical_set(self, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "x")
        monkeypatch.delenv("HERMES_FOO", raising=False)
        assert which_env_set("FOO") == "SIMPLICIO_AGENT_FOO"

    def test_both_set_reports_canonical(self, monkeypatch):
        monkeypatch.setenv("SIMPLICIO_AGENT_FOO", "x")
        monkeypatch.setenv("HERMES_FOO", "y")
        assert which_env_set("FOO") == "SIMPLICIO_AGENT_FOO"


def test_name_helpers():
    assert canonical_env_name("HOME") == "SIMPLICIO_AGENT_HOME"
    assert legacy_env_name("HOME") == "HERMES_HOME"
