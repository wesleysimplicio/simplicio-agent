"""Tests for agent.state_migration — one-shot ~/.hermes -> ~/.simplicio/agent
copy-then-mark migrator (issue #117)."""

from __future__ import annotations

import json
import os

import pytest

from agent.state_migration import (
    MARKER_NAME,
    canonical_new_home,
    migrate_default_state,
    migrate_state,
)


def _populate_legacy(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("model: deepseek-chat\n")
    profiles = root / "profiles" / "coder"
    profiles.mkdir(parents=True)
    (profiles / "config.yaml").write_text("model: coder\n")
    sessions = root / "sessions"
    sessions.mkdir()
    (sessions / "sessions.json").write_text("{}")


class TestMigrateState:
    def test_fresh_install_nothing_to_migrate(self, tmp_path):
        legacy = tmp_path / "hermes"  # never created
        new = tmp_path / "simplicio" / "agent"
        report = migrate_state(legacy, new)
        assert report.migrated is False
        assert report.already_migrated is False
        assert report.skipped_reason and "no legacy state" in report.skipped_reason
        assert not new.exists()

    def test_real_migration_copies_everything(self, tmp_path):
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        report = migrate_state(legacy, new)

        assert report.migrated is True
        assert not report.errors
        assert set(report.copied_entries) == {"config.yaml", "profiles", "sessions"}
        assert (new / "config.yaml").read_text() == "model: deepseek-chat\n"
        assert (new / "profiles" / "coder" / "config.yaml").read_text() == "model: coder\n"
        assert (new / "sessions" / "sessions.json").read_text() == "{}"
        # Non-destructive: legacy is untouched.
        assert (legacy / "config.yaml").exists()
        assert (legacy / "profiles" / "coder" / "config.yaml").exists()
        # Marker written with real, inspectable metadata (no secret values).
        marker = new / MARKER_NAME
        assert marker.exists()
        payload = json.loads(marker.read_text())
        assert payload["schema"] == "simplicio.state-migration/v1"
        assert payload["source"] == str(legacy)
        assert set(payload["entries"]) == {"config.yaml", "profiles", "sessions"}

    def test_second_call_is_idempotent_noop(self, tmp_path):
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        first = migrate_state(legacy, new)
        assert first.migrated is True

        # Mutate legacy after migration — a no-op second run must not re-copy.
        (legacy / "config.yaml").write_text("model: changed-after-migration\n")

        second = migrate_state(legacy, new)
        assert second.already_migrated is True
        assert second.migrated is False
        # The new root keeps its already-migrated content, unaffected by the
        # post-migration legacy mutation.
        assert (new / "config.yaml").read_text() == "model: deepseek-chat\n"

    def test_interrupted_migration_resumes_without_duplicating(self, tmp_path):
        """Simulate a kill mid-copy: no marker was written, so a retry must
        finish the job (copy-then-mark, never a destructive move)."""
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        # Simulate a partial prior run: only "config.yaml" made it across,
        # no marker written (as if the process died right after that copy).
        new.mkdir(parents=True)
        (new / "config.yaml").write_text("model: deepseek-chat\n")
        assert not (new / MARKER_NAME).exists()

        report = migrate_state(legacy, new)

        assert report.migrated is True
        assert (new / "profiles" / "coder" / "config.yaml").exists()
        assert (new / "sessions" / "sessions.json").exists()
        assert (new / MARKER_NAME).exists()

    def test_no_migrate_opt_out_skips_and_touches_nothing(self, tmp_path):
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        report = migrate_state(legacy, new, no_migrate=True)

        assert report.migrated is False
        assert report.skipped_reason and "no-migrate" in report.skipped_reason.lower() \
            or "NO_MIGRATE" in (report.skipped_reason or "")
        assert not new.exists()
        assert (legacy / "config.yaml").exists()  # legacy still intact

    def test_dry_run_reports_without_writing(self, tmp_path):
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        report = migrate_state(legacy, new, dry_run=True)

        assert report.dry_run is True
        assert report.migrated is False
        assert set(report.copied_entries) == {"config.yaml", "profiles", "sessions"}
        assert not new.exists()

    def test_same_source_and_destination_is_a_noop(self, tmp_path):
        same = tmp_path / "hermes"
        _populate_legacy(same)

        report = migrate_state(same, same)

        assert report.migrated is False
        assert report.skipped_reason and "same path" in report.skipped_reason

    def test_empty_legacy_dir_is_treated_as_nothing_to_migrate(self, tmp_path):
        legacy = tmp_path / "hermes"
        legacy.mkdir()
        new = tmp_path / "simplicio" / "agent"

        report = migrate_state(legacy, new)

        assert report.migrated is False
        assert report.skipped_reason and "no legacy state" in report.skipped_reason

    def test_legacy_file_conflicts_do_not_crash_and_are_reported(self, tmp_path, monkeypatch):
        """An OSError while copying one entry is captured, not raised, and the
        marker is withheld so a retry can finish the job."""
        legacy = tmp_path / "hermes"
        new = tmp_path / "simplicio" / "agent"
        _populate_legacy(legacy)

        import shutil as shutil_mod

        real_copy2 = shutil_mod.copy2

        def flaky_copy2(src, dst, *a, **kw):
            if str(src).endswith("config.yaml") and "profiles" not in str(src):
                raise OSError("simulated disk full")
            return real_copy2(src, dst, *a, **kw)

        monkeypatch.setattr("agent.state_migration.shutil.copy2", flaky_copy2)

        report = migrate_state(legacy, new)

        assert report.migrated is False
        assert report.errors
        assert not (new / MARKER_NAME).exists()
        # The directory entries (profiles/sessions) still succeeded.
        assert (new / "profiles" / "coder" / "config.yaml").exists()


class TestCanonicalNewHome:
    def test_posix_default(self, monkeypatch):
        monkeypatch.setattr("agent.state_migration.sys.platform", "linux")
        monkeypatch.setattr("agent.state_migration.Path.home", lambda: __import__("pathlib").Path("/home/u"))
        assert canonical_new_home() == __import__("pathlib").Path("/home/u/.simplicio/agent")

    def test_windows_uses_localappdata(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent.state_migration.sys.platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert canonical_new_home() == tmp_path / "simplicio" / "agent"


class TestMigrateDefaultState:
    def test_wires_real_legacy_home_and_canonical_target(self, tmp_path, monkeypatch):
        legacy = tmp_path / "hermes-home"
        _populate_legacy(legacy)
        monkeypatch.setenv("HERMES_HOME", str(legacy))
        monkeypatch.delenv("SIMPLICIO_AGENT_HOME", raising=False)
        monkeypatch.delenv("SIMPLICIO_AGENT_NO_MIGRATE", raising=False)
        monkeypatch.delenv("HERMES_NO_MIGRATE", raising=False)

        new_home = tmp_path / "simplicio-new"
        monkeypatch.setattr("agent.state_migration.canonical_new_home", lambda: new_home)

        report = migrate_default_state()

        assert report.migrated is True
        assert report.source == legacy
        assert report.dest == new_home
        assert (new_home / "config.yaml").exists()

    def test_no_migrate_env_alias_opts_out(self, tmp_path, monkeypatch):
        legacy = tmp_path / "hermes-home"
        _populate_legacy(legacy)
        monkeypatch.setenv("HERMES_HOME", str(legacy))
        monkeypatch.setenv("SIMPLICIO_AGENT_NO_MIGRATE", "1")

        new_home = tmp_path / "simplicio-new"
        monkeypatch.setattr("agent.state_migration.canonical_new_home", lambda: new_home)

        report = migrate_default_state()

        assert report.migrated is False
        assert not new_home.exists()
