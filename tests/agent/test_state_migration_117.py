"""Tests for #117 additions to agent.state_migration:
- symlink escape guard (_symlink_escapes / _copy_to_stage behavior)
- secret-path permission hardening (_is_secret_path / _harden_permissions)
- migration_doctor() read-only inspector
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent.state_migration import (
    DoctorReport,
    MARKER_NAME,
    _harden_permissions,
    _is_secret_path,
    _symlink_escapes,
    migration_doctor,
    migrate_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populate_legacy(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("model: deepseek-chat\n")
    profiles = root / "profiles" / "coder"
    profiles.mkdir(parents=True)
    (profiles / "config.yaml").write_text("model: coder\n")
    sessions = root / "sessions"
    sessions.mkdir()
    (sessions / "sessions.json").write_text("{}")


# ---------------------------------------------------------------------------
# Symlink escape guard
# ---------------------------------------------------------------------------

class TestSymlinkEscapeGuard:
    def test_internal_symlink_does_not_escape(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target = root / "real.txt"
        target.write_text("hi")
        link = root / "alias.txt"
        link.symlink_to(target)
        assert _symlink_escapes(link, root) is False

    def test_external_symlink_escapes(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = root / "escape.txt"
        link.symlink_to(outside)
        assert _symlink_escapes(link, root) is True

    def test_escaping_symlink_is_skipped_during_copy(self, tmp_path):
        """An escaping symlink must not appear in the staging directory."""
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("external content")
        escape_link = legacy / "escape.txt"
        escape_link.symlink_to(outside)
        # Also add a normal file so we can assert partial copy worked.
        (legacy / "normal.txt").write_text("normal")

        new = tmp_path / "new"
        report = migrate_state(legacy, new)

        assert report.migrated is True
        # Normal file must be copied.
        assert (new / "normal.txt").exists()
        # Escaping symlink must NOT appear in the destination.
        assert not (new / "escape.txt").exists()

    def test_internal_symlink_is_preserved_during_copy(self, tmp_path):
        """A symlink pointing inside the source root must be replicated."""
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        real = legacy / "real.txt"
        real.write_text("data")
        # Create a symlink inside the same root pointing at the real file.
        link = legacy / "alias.txt"
        link.symlink_to(real)

        new = tmp_path / "new"
        report = migrate_state(legacy, new)

        # Both the real file and the within-root symlink should reach destination.
        assert report.migrated is True
        assert (new / "real.txt").read_text() == "data"
        assert (new / "alias.txt").is_symlink()


# ---------------------------------------------------------------------------
# Secret permission hardening
# ---------------------------------------------------------------------------

class TestSecretPermissions:
    @pytest.mark.parametrize(
        "name",
        ["secrets", "auth", "credentials", "key.pem", "id.token", "private.key"],
    )
    def test_is_secret_path_positive(self, name, tmp_path):
        assert _is_secret_path(tmp_path / name)

    @pytest.mark.parametrize("name", ["config.yaml", "sessions", "profiles"])
    def test_is_secret_path_negative(self, name, tmp_path):
        assert not _is_secret_path(tmp_path / name)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_harden_permissions_file(self, tmp_path):
        f = tmp_path / "key.pem"
        f.write_text("--- BEGIN ---")
        os.chmod(f, 0o644)
        _harden_permissions(f)
        mode = stat.S_IMODE(os.stat(f).st_mode)
        assert mode == 0o600

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_harden_permissions_dir(self, tmp_path):
        d = tmp_path / "secrets"
        d.mkdir()
        os.chmod(d, 0o755)
        _harden_permissions(d)
        mode = stat.S_IMODE(os.stat(d).st_mode)
        assert mode == 0o700

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_secrets_dir_is_hardened_after_migration(self, tmp_path):
        """After a full migration, a 'secrets' dir must land at mode 0o700."""
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        secrets_dir = legacy / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "api.token").write_text("supersecret")
        os.chmod(secrets_dir, 0o755)

        new = tmp_path / "new"
        report = migrate_state(legacy, new)

        assert report.migrated is True
        dest_secrets = report.staging_path / "secrets"
        assert dest_secrets.exists()
        mode = stat.S_IMODE(os.stat(dest_secrets).st_mode)
        assert mode == 0o700


# ---------------------------------------------------------------------------
# migration_doctor
# ---------------------------------------------------------------------------

class TestMigrationDoctor:
    def test_fresh_install_nothing_to_report(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy"  # does not exist
        new = tmp_path / "new"
        report = migration_doctor(legacy, new)
        assert isinstance(report, DoctorReport)
        assert not report.legacy_exists
        assert not report.new_exists
        assert not report.already_migrated
        assert not report.staging_exists
        assert not report.errors

    def test_pending_migration_shows_conflicts(self, tmp_path):
        legacy = tmp_path / "legacy"
        _populate_legacy(legacy)
        new = tmp_path / "new"
        new.mkdir()
        (new / "config.yaml").write_text("different content\n")

        report = migration_doctor(legacy, new)
        assert report.legacy_exists
        assert report.new_exists
        assert not report.already_migrated
        assert "config.yaml" in report.conflicts

    def test_completed_migration_shows_migrated(self, tmp_path):
        legacy = tmp_path / "legacy"
        new = tmp_path / "new"
        _populate_legacy(legacy)
        migrate_state(legacy, new)

        report = migration_doctor(legacy, new)
        assert report.already_migrated
        assert not report.conflicts

    def test_summary_contains_key_fields(self, tmp_path):
        legacy = tmp_path / "legacy"
        _populate_legacy(legacy)
        new = tmp_path / "new"
        report = migration_doctor(legacy, new)
        text = report.summary()
        assert "legacy_home" in text
        assert "new_home" in text
        assert "migrated" in text

    def test_doctor_reads_manifest_status_after_interrupted_run(self, tmp_path, monkeypatch):
        """After a failed (interrupted) run the doctor must surface manifest status."""
        legacy = tmp_path / "legacy"
        new = tmp_path / "new"
        _populate_legacy(legacy)

        real_copy2 = __import__("shutil").copy2

        def fail_first(src, dst, *a, **kw):
            raise OSError("simulated failure")

        monkeypatch.setattr("agent.state_migration.shutil.copy2", fail_first)
        migrate_state(legacy, new)
        monkeypatch.setattr("agent.state_migration.shutil.copy2", real_copy2)

        report = migration_doctor(legacy, new)
        # staging workspace was created; manifest should record a non-null status
        assert report.manifest_status is not None
