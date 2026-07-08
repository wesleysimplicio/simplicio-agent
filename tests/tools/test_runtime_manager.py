"""Tests for tools/runtime_manager.py -- the managed runtime dependency
(ADR-0003).

Covers: runtime.lock loading/degradation, semver handshake, the
env > PATH > managed-dir resolution order, RuntimeStatus outcomes, the
never-overwrite-user-installs rule, and honest install failure reporting.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

import tools.kernel_binding as kb
import tools.runtime_manager as rm


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
    monkeypatch.delenv("SIMPLICIO_HOME", raising=False)
    kb.reset_kernel_cache()
    rm.reset_bootstrap()
    yield
    kb.reset_kernel_cache()
    rm.reset_bootstrap()


def _write_lock(tmp_path, monkeypatch, **overrides):
    data = {
        "schema": "runtime-lock/v1",
        "kernel": "simplicio",
        "min_version": "3.4.0",
        "release_repo": "wesleysimplicio/simplicio",
        "source_repo": "wesleysimplicio/simplicio-runtime",
        "assets": {"darwin-arm64": "simplicio-macos-arm64"},
        "sibling_checkout": "../simplicio-runtime",
    }
    data.update(overrides)
    (tmp_path / "runtime.lock").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
    return data


def _fake_managed_kernel(tmp_path, monkeypatch, name="simplicio"):
    """Drop an executable stub into a fake SIMPLICIO_HOME/bin."""
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
    bin_dir = rm.managed_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    bin_name = f"{name}.exe" if sys.platform == "win32" else name
    stub = bin_dir / bin_name
    stub.write_text("#!/bin/sh\necho simplicio 9.9.9\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


# =========================================================================
# runtime.lock
# =========================================================================

class TestLoadRuntimeLock:
    def test_reads_pin_from_repo_root(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch, min_version="7.1.2")
        assert rm.load_runtime_lock()["min_version"] == "7.1.2"

    def test_missing_lock_degrades_to_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
        lock = rm.load_runtime_lock()
        assert lock["min_version"] == "0.0.0"
        assert lock["kernel"] == "simplicio"

    def test_corrupt_lock_degrades_to_defaults(self, tmp_path, monkeypatch):
        (tmp_path / "runtime.lock").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
        assert rm.load_runtime_lock()["min_version"] == "0.0.0"

    def test_real_repo_lock_is_valid(self):
        # The committed runtime.lock must always parse and carry a real pin.
        lock = rm.load_runtime_lock()
        assert lock["schema"] == "runtime-lock/v1"
        assert rm.parse_semver(lock["min_version"]) is not None


# =========================================================================
# semver handshake
# =========================================================================

class TestVersionHandshake:
    @pytest.mark.parametrize("text,expected", [
        ("simplicio 3.4.0", (3, 4, 0)),
        ("v10.0.2\n", (10, 0, 2)),
        ("garbage", None),
        ("", None),
    ])
    def test_parse_semver(self, text, expected):
        assert rm.parse_semver(text) == expected

    @pytest.mark.parametrize("installed,minimum,ok", [
        ("3.4.0", "3.4.0", True),
        ("3.5.1", "3.4.0", True),
        ("4.0.0", "3.9.9", True),
        ("3.3.9", "3.4.0", False),
        ("garbage", "3.4.0", False),
        ("3.4.0", "not-a-pin", True),  # unparseable pin never blocks
    ])
    def test_version_satisfies(self, installed, minimum, ok):
        assert rm.version_satisfies(installed, minimum) is ok

    def test_kernel_version_parses_stdout(self):
        proc = subprocess.CompletedProcess([], 0, stdout="simplicio 3.4.0\n", stderr="")
        with mock_patch("subprocess.run", return_value=proc):
            assert rm.kernel_version("/bin/simplicio") == "3.4.0"

    def test_kernel_version_none_on_failure(self):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock_patch("subprocess.run", return_value=proc):
            assert rm.kernel_version("/bin/simplicio") is None

    def test_kernel_version_accepts_runtime_suffix_and_v_prefix(self):
        proc = subprocess.CompletedProcess([], 0, stdout="simplicio-runtime v3.5.1\n", stderr="")
        with mock_patch("subprocess.run", return_value=proc):
            assert rm.kernel_version("/bin/simplicio") == "3.5.1"

    def test_kernel_version_rejects_homonym_binary_banner(self):
        """Identity handshake (adversarial review #4): a binary that shares
        the name but isn't the kernel must not satisfy the pin just because
        a version-shaped substring appears somewhere in its output."""
        proc = subprocess.CompletedProcess(
            [], 0, stdout="Simplicio Agent v0.17.0\nPython 3.11\n", stderr="",
        )
        with mock_patch("subprocess.run", return_value=proc):
            assert rm.kernel_version("/bin/simplicio") is None

    def test_kernel_version_ignores_stderr_only_version(self):
        """The banner must come from stdout -- stderr is not trusted for
        identity, only for diagnostics."""
        proc = subprocess.CompletedProcess(
            [], 0, stdout="", stderr="simplicio 3.4.0\n",
        )
        with mock_patch("subprocess.run", return_value=proc):
            assert rm.kernel_version("/bin/simplicio") is None


# =========================================================================
# resolution order: env > PATH > managed dir
# =========================================================================

class TestResolveKernel:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        lock = _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("HERMES_KERNEL_BIN", "simplicio-dev")
        with mock_patch("shutil.which", return_value="/opt/simplicio-dev"):
            assert rm.resolve_kernel(lock) == ("/opt/simplicio-dev", "env")

    def test_path_before_managed(self, tmp_path, monkeypatch):
        lock = _write_lock(tmp_path, monkeypatch)
        _fake_managed_kernel(tmp_path, monkeypatch)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"):
            assert rm.resolve_kernel(lock) == ("/usr/bin/simplicio", "path")

    def test_managed_dir_fallback(self, tmp_path, monkeypatch):
        lock = _write_lock(tmp_path, monkeypatch)
        stub = _fake_managed_kernel(tmp_path, monkeypatch)
        with mock_patch("shutil.which", return_value=None):
            path, source = rm.resolve_kernel(lock)
        assert source == "managed"
        assert path == str(stub)

    def test_absent(self, tmp_path, monkeypatch):
        lock = _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "empty"))
        with mock_patch("shutil.which", return_value=None):
            assert rm.resolve_kernel(lock) == (None, "absent")

    def test_kernel_binding_sees_managed_install(self, tmp_path, monkeypatch):
        """resolve_kernel_bin (the binding layer) must find the managed
        install so every existing binding lights up without PATH edits."""
        stub = _fake_managed_kernel(tmp_path, monkeypatch)
        with mock_patch("shutil.which", return_value=None):
            assert kb.resolve_kernel_bin() == str(stub)


# =========================================================================
# runtime_status
# =========================================================================

class TestRuntimeStatus:
    def test_satisfied(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch, min_version="3.4.0")
        with mock_patch.object(rm, "resolve_kernel", return_value=("/bin/simplicio", "path")), \
             mock_patch.object(rm, "kernel_version", return_value="3.5.0"):
            st = rm.runtime_status()
        assert st.satisfied and st.present
        assert st.source == "path" and st.version == "3.5.0"

    def test_stale(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch, min_version="3.4.0")
        with mock_patch.object(rm, "resolve_kernel", return_value=("/bin/simplicio", "path")), \
             mock_patch.object(rm, "kernel_version", return_value="3.3.0"):
            st = rm.runtime_status()
        assert st.present and not st.satisfied
        assert "3.3.0" in st.detail and "3.4.0" in st.detail

    def test_absent(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        with mock_patch.object(rm, "resolve_kernel", return_value=(None, "absent")):
            st = rm.runtime_status()
        assert not st.present and not st.satisfied

    def test_handshake_failure(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        with mock_patch.object(rm, "resolve_kernel", return_value=("/bin/simplicio", "path")), \
             mock_patch.object(rm, "kernel_version", return_value=None):
            st = rm.runtime_status()
        assert st.present and not st.satisfied
        assert "handshake" in st.detail


# =========================================================================
# ensure_runtime
# =========================================================================

class TestEnsureRuntime:
    def test_noop_when_satisfied(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        good = rm.RuntimeStatus("/bin/simplicio", "path", "3.4.0", "3.4.0", True)
        with mock_patch.object(rm, "runtime_status", return_value=good), \
             mock_patch.object(rm, "_install_from_release") as rel, \
             mock_patch.object(rm, "_install_from_sibling") as sib:
            st = rm.ensure_runtime(install=True)
        assert st.satisfied
        rel.assert_not_called()
        sib.assert_not_called()

    def test_status_only_without_install(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        stale = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=stale), \
             mock_patch.object(rm, "_install_from_release") as rel:
            st = rm.ensure_runtime(install=False)
        assert not st.satisfied
        rel.assert_not_called()

    def test_never_overwrites_user_managed_install(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        stale_path = rm.RuntimeStatus("/usr/bin/simplicio", "path", "3.0.0", "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=stale_path), \
             mock_patch.object(rm, "_install_from_release") as rel:
            st = rm.ensure_runtime(install=True)
        assert not st.satisfied
        assert "user-managed" in st.detail
        rel.assert_not_called()

    def test_release_then_sibling_fallback_reports_both(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=absent), \
             mock_patch.object(rm, "_install_from_release", return_value="no gh"), \
             mock_patch.object(rm, "_install_from_sibling", return_value="no cargo"):
            st = rm.ensure_runtime(install=True)
        assert not st.satisfied
        assert "no gh" in st.detail and "no cargo" in st.detail

    def test_successful_install_rehandshakes(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        fresh = rm.RuntimeStatus(
            str(tmp_path / "simplicio-home" / "bin" / "simplicio"),
            "managed", "3.4.0", "3.4.0", True,
        )
        with mock_patch.object(rm, "runtime_status", side_effect=[absent, fresh]), \
             mock_patch.object(rm, "_install_from_release", return_value=None):
            st = rm.ensure_runtime(install=True)
        assert st.satisfied and st.source == "managed"

    def test_platform_asset_mapping(self, tmp_path, monkeypatch):
        lock = _write_lock(
            tmp_path, monkeypatch,
            assets={"darwin-arm64": "simplicio-macos-arm64", "linux-x86_64": "simplicio"},
        )
        with mock_patch("platform.system", return_value="Darwin"), \
             mock_patch("platform.machine", return_value="arm64"):
            assert rm._platform_asset(lock) == "simplicio-macos-arm64"
        with mock_patch("platform.system", return_value="Linux"), \
             mock_patch("platform.machine", return_value="amd64"):
            assert rm._platform_asset(lock) == "simplicio"
        with mock_patch("platform.system", return_value="Windows"), \
             mock_patch("platform.machine", return_value="AMD64"):
            assert rm._platform_asset(lock) is None


# =========================================================================
# _install_from_release -- supply-chain verification (adversarial review #1)
# =========================================================================

class TestInstallFromReleaseSha256:
    _ASSET_KEY = "testsys-testarch"

    def _lock(self, sha256):
        entry = {"name": "simplicio-bin"}
        if sha256 is not None:
            entry["sha256"] = sha256
        return {
            "assets": {self._ASSET_KEY: entry},
            "release_repo": "wesleysimplicio/simplicio",
        }

    def _patched_platform(self):
        return (
            mock_patch("platform.system", return_value="Testsys"),
            mock_patch("platform.machine", return_value="testarch"),
        )

    def test_no_pinned_sha256_refuses_install(self, tmp_path):
        lock = self._lock(sha256=None)
        dest = tmp_path / "simplicio"
        p1, p2 = self._patched_platform()
        with p1, p2, mock_patch("shutil.which", return_value="/usr/bin/gh") as which, \
             mock_patch("subprocess.run") as run:
            err = rm._install_from_release(lock, dest)
        assert err is not None
        assert "no pinned sha256" in err
        # Never even attempts the download without a pinned hash.
        run.assert_not_called()
        assert not dest.exists()

    def test_sha256_mismatch_removes_tmp_and_errors(self, tmp_path):
        lock = self._lock(sha256="0" * 64)
        dest = tmp_path / "simplicio"

        def fake_run(cmd, **kwargs):
            out_idx = cmd.index("--output") + 1
            Path(cmd[out_idx]).write_bytes(b"not-the-real-binary-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        p1, p2 = self._patched_platform()
        with p1, p2, mock_patch("shutil.which", return_value="/usr/bin/gh"), \
             mock_patch("subprocess.run", side_effect=fake_run):
            err = rm._install_from_release(lock, dest)

        assert err is not None
        assert "sha256 mismatch" in err
        assert not dest.exists()
        leftover = list(tmp_path.glob(".simplicio.download.*"))
        assert leftover == [], f"tmp download not cleaned up: {leftover}"

    def test_sha256_match_installs(self, tmp_path):
        payload = b"the-real-binary-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        lock = self._lock(sha256=digest)
        dest = tmp_path / "simplicio"

        def fake_run(cmd, **kwargs):
            out_idx = cmd.index("--output") + 1
            Path(cmd[out_idx]).write_bytes(payload)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        p1, p2 = self._patched_platform()
        with p1, p2, mock_patch("shutil.which", return_value="/usr/bin/gh"), \
             mock_patch("subprocess.run", side_effect=fake_run):
            err = rm._install_from_release(lock, dest)

        assert err is None
        assert dest.read_bytes() == payload
        leftover = list(tmp_path.glob(".simplicio.download.*"))
        assert leftover == []

    def test_legacy_plain_string_asset_has_no_pinned_hash(self, tmp_path):
        """Back-compat: a bare-string asset entry (no object) is treated as
        having no pinned hash, so it's refused, not installed blind."""
        lock = {
            "assets": {self._ASSET_KEY: "simplicio-bin"},
            "release_repo": "wesleysimplicio/simplicio",
        }
        dest = tmp_path / "simplicio"
        p1, p2 = self._patched_platform()
        with p1, p2, mock_patch("shutil.which", return_value="/usr/bin/gh"), \
             mock_patch("subprocess.run") as run:
            err = rm._install_from_release(lock, dest)
        assert err is not None
        assert "no pinned sha256" in err
        run.assert_not_called()


# =========================================================================
# bootstrap_session -- the startup handshake (agent always runs w/ runtime)
# =========================================================================

class TestBootstrapSession:
    def test_quiet_when_satisfied(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        good = rm.RuntimeStatus("/bin/simplicio", "path", "3.4.0", "3.4.0", True)
        with mock_patch.object(rm, "runtime_status", return_value=good):
            assert rm.bootstrap_session() is None

    def test_warns_when_absent(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        absent = rm.RuntimeStatus(
            None, "absent", None, "3.4.0", False,
            detail="kernel binary not found",
        )
        with mock_patch.object(rm, "runtime_status", return_value=absent):
            warning = rm.bootstrap_session()
        assert warning is not None
        assert "3.4.0" in warning
        assert "doctor --fix" in warning

    def test_absent_kernel_never_auto_installs(self, tmp_path, monkeypatch):
        """Adversarial review #1c: bootstrap is a handshake only. It must
        never call the install path -- that requires explicit consent via
        `simplicio-agent doctor --fix` (ensure_runtime(install=True))."""
        _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=absent), \
             mock_patch.object(rm, "_install_from_release") as rel, \
             mock_patch.object(rm, "_install_from_sibling") as sib:
            warning = rm.bootstrap_session()
        assert warning is not None
        rel.assert_not_called()
        sib.assert_not_called()

    def test_stale_user_managed_warns_without_install(self, tmp_path, monkeypatch):
        """A stale PATH kernel is reported, never replaced at startup."""
        _write_lock(tmp_path, monkeypatch)
        stale = rm.RuntimeStatus(
            "/usr/bin/simplicio", "path", "0.17.0", "3.4.0", False,
            detail="installed 0.17.0 < pinned 3.4.0",
        )
        with mock_patch.object(rm, "runtime_status", return_value=stale), \
             mock_patch.object(rm, "_install_from_release") as rel:
            warning = rm.bootstrap_session()
        assert warning is not None and "0.17.0" in warning
        rel.assert_not_called()

    def test_runs_once_per_process(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=absent) as st, \
             mock_patch.object(rm, "_install_from_release", return_value="err"):
            rm.bootstrap_session()
            first_calls = st.call_count
            assert rm.bootstrap_session() is None  # latched
            assert st.call_count == first_calls

    def test_never_raises(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        with mock_patch.object(rm, "runtime_status", side_effect=RuntimeError("boom")):
            assert rm.bootstrap_session() is None

