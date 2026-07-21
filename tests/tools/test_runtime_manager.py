"""Tests for tools/runtime_manager.py -- the managed runtime dependency
(ADR-0003).

Covers: runtime.lock loading/degradation, semver handshake, the
env > PATH > managed-dir resolution order, RuntimeStatus outcomes, the
never-overwrite-user-installs rule, and honest install failure reporting.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

import tools.kernel_binding as kb
import tools.runtime_manager as rm
from tools.runtime_handshake import (
    HANDSHAKE_PROTOCOL_STATUS_UNREPORTED,
    HANDSHAKE_REASON_HANDSHAKE_FAILED,
    HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME,
    HANDSHAKE_REASON_READY,
    HANDSHAKE_REASON_RUNTIME_MISSING,
)


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
    payload = b"runtime"
    target = rm._target_key()
    data = {
        "schema": "runtime-lock/v2",
        "kernel": "simplicio",
        "min_version": "3.4.0",
        "release_repo": "wesleysimplicio/simplicio",
        "source_repo": "wesleysimplicio/simplicio-runtime",
        "assets": {
            target: {
                "name": "simplicio-test",
                "version": "3.4.0",
                "url": "https://example.invalid/releases/download/v3.4.0/simplicio-test",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "target": {"os": target.split("-", 1)[0], "arch": target.split("-", 1)[1]},
            }
        },
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


def _require_symlink_support(tmp_path):
    probe_target = tmp_path / "symlink-target.txt"
    probe_link = tmp_path / "symlink-probe"
    probe_target.write_text("probe", encoding="utf-8")
    try:
        probe_link.symlink_to(probe_target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation is not permitted on this Windows host")
        raise
    else:
        probe_link.unlink()
        probe_target.unlink()


# =========================================================================
# runtime.lock
# =========================================================================

class TestLoadRuntimeLock:
    def test_reads_pin_from_repo_root(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch, min_version="7.1.2")
        assert rm.load_runtime_lock()["min_version"] == "7.1.2"


    def test_reads_pin_from_installed_data_file(self, tmp_path, monkeypatch):
        source_root = tmp_path / "source"
        source_root.mkdir()
        prefix = tmp_path / "prefix"
        installed_lock = prefix / "runtime" / "runtime.lock"
        installed_lock.parent.mkdir(parents=True)
        installed_lock.write_text(json.dumps({"schema": "runtime-lock/v2", "min_version": "8.2.1"}), encoding="utf-8")
        monkeypatch.setattr(rm, "repo_root", lambda: source_root)
        monkeypatch.setattr(rm.sys, "prefix", str(prefix))

        assert rm.load_runtime_lock()["min_version"] == "8.2.1"
    def test_missing_lock_does_not_manufacture_a_pin(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
        assert rm.load_runtime_lock() == {}

    def test_corrupt_lock_does_not_manufacture_a_pin(self, tmp_path, monkeypatch):
        (tmp_path / "runtime.lock").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
        assert rm.load_runtime_lock() == {}

    def test_missing_lock_blocks_resolution_before_any_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rm, "repo_root", lambda: tmp_path)
        with mock_patch.object(rm, "resolve_kernel") as resolve:
            status = rm.runtime_status()
        assert not status.satisfied
        assert not status.lock_valid
        assert "runtime lock invalid" in status.detail
        resolve.assert_not_called()

    def test_real_repo_lock_is_valid(self):
        # The committed runtime.lock must always parse and carry a real pin.
        lock = rm.load_runtime_lock()
        assert lock["schema"] == "runtime-lock/v2"
        assert rm.parse_semver(lock["min_version"]) is not None

    def test_rejects_null_required_asset_metadata(self):
        lock = {
            "schema": "runtime-lock/v2",
            "kernel": "simplicio",
            "min_version": "3.5.2",
            "assets": {
                "linux-x86_64": {
                    "name": "simplicio",
                    "version": "3.5.2",
                    "url": None,
                    "sha256": None,
                    "size": None,
                    "target": {"os": "linux", "arch": "x86_64"},
                }
            },
        }
        result = rm.validate_runtime_lock(lock, target="linux-x86_64")
        assert not result.valid
        assert "url must be non-null" in result.detail
        assert "sha256 must be non-null" in result.detail
        assert "size must be non-null" in result.detail

    def test_rejects_wrong_target_metadata(self):
        lock = {
            "schema": "runtime-lock/v2",
            "kernel": "simplicio",
            "min_version": "3.5.2",
            "assets": {
                "linux-x86_64": {
                    "name": "simplicio",
                    "version": "3.5.2",
                    "url": "https://example.invalid/simplicio",
                    "sha256": "a" * 64,
                    "size": 1,
                    "target": {"os": "darwin", "arch": "arm64"},
                }
            },
        }
        result = rm.validate_runtime_lock(lock, target="linux-x86_64")
        assert not result.valid
        assert "does not match its target key" in result.detail


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

    def test_kernel_version_falls_back_to_legacy_version_command(self):
        responses = [
            subprocess.CompletedProcess([], 1, stdout="", stderr="unknown option"),
            subprocess.CompletedProcess([], 0, stdout="simplicio-runtime 1.6.4\n", stderr=""),
        ]
        with mock_patch("subprocess.run", side_effect=responses) as run:
            assert rm.kernel_version("/bin/simplicio") == "1.6.4"
        assert run.call_args_list[0].args[0][-1] == "--version"
        assert run.call_args_list[1].args[0][-1] == "version"

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

    def test_kernel_version_accepts_real_runtime_banner(self):
        """The shipped kernel prints 'Simplicio Runtime X.Y.Z' (note the
        'Runtime' word between the name and the version). Older builds print
        'simplicio vX.Y.Z' / 'simplicio-runtime vX.Y.Z'. All must parse."""
        for banner in (
            "Simplicio Runtime 3.5.0\n",
            "simplicio 3.4.0\n",
            "simplicio-runtime v3.5.1\n",
        ):
            proc = subprocess.CompletedProcess([], 0, stdout=banner, stderr="")
            with mock_patch("subprocess.run", return_value=proc):
                assert rm.kernel_version("/bin/simplicio") is not None

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
        binary = tmp_path / "simplicio"
        binary.write_bytes(b"runtime")
        with mock_patch.object(rm, "resolve_kernel", return_value=(str(binary), "path")), \
             mock_patch.object(rm, "kernel_version", return_value="3.5.0"):
            st = rm.runtime_status()
        assert st.satisfied and st.present
        assert st.source == "path" and st.version == "3.5.0"
        assert st.verified and st.ready and st.lock_valid
        assert st.reason_code == HANDSHAKE_REASON_READY
        assert st.handshake is not None
        assert st.handshake.protocol_status == HANDSHAKE_PROTOCOL_STATUS_UNREPORTED

    def test_stale(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch, min_version="3.4.0")
        binary = tmp_path / "simplicio"
        binary.write_bytes(b"runtime")
        with mock_patch.object(rm, "resolve_kernel", return_value=(str(binary), "path")), \
             mock_patch.object(rm, "kernel_version", return_value="3.3.0"):
            st = rm.runtime_status()
        assert st.present and not st.satisfied
        assert "3.3.0" in st.detail and "3.4.0" in st.detail
        assert st.reason_code == HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME
        assert st.handshake is not None
        assert st.handshake.to_dict()["reason_code"] == HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME

    def test_absent(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        with mock_patch.object(rm, "resolve_kernel", return_value=(None, "absent")):
            st = rm.runtime_status()
        assert not st.present and not st.satisfied
        assert st.reason_code == HANDSHAKE_REASON_RUNTIME_MISSING

    def test_handshake_failure(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        binary = tmp_path / "simplicio"
        binary.write_bytes(b"runtime")
        with mock_patch.object(rm, "resolve_kernel", return_value=(str(binary), "path")), \
             mock_patch.object(rm, "kernel_version", return_value=None):
            st = rm.runtime_status()
        assert st.present and not st.satisfied
        assert "handshake" in st.detail
        assert st.reason_code == HANDSHAKE_REASON_HANDSHAKE_FAILED

    def test_tampered_binary_is_rejected_before_handshake(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        binary = tmp_path / "simplicio"
        binary.write_bytes(b"tamper!")
        with mock_patch.object(rm, "resolve_kernel", return_value=(str(binary), "path")), \
             mock_patch.object(rm, "kernel_version") as version:
            st = rm.runtime_status()
        assert not st.satisfied and not st.verified
        assert "sha256 mismatch" in st.detail
        version.assert_not_called()

    def test_unsupported_target_is_not_replaced_by_wrong_target(self, tmp_path, monkeypatch):
        # Force the "current" target to something the lock's only asset does
        # NOT match, regardless of the host this test actually runs on — a
        # hardcoded "darwin-arm64" asset would coincidentally *match* the real
        # target on an Apple Silicon Mac (and find a real installed kernel
        # binary via PATH), defeating the "unsupported target" premise.
        monkeypatch.setattr(rm, "_target_key", lambda *a, **k: "linux-x64")
        lock = _write_lock(tmp_path, monkeypatch)
        lock["assets"] = {
            "darwin-arm64": {
                "name": "simplicio-macos-arm64",
                "version": "3.5.2",
                "url": "https://example.invalid/releases/download/v3.5.2/simplicio-macos-arm64",
                "sha256": "a" * 64,
                "size": 1,
                "target": {"os": "darwin", "arch": "arm64"},
            }
        }
        st = rm.runtime_status(lock)
        assert not st.satisfied
        assert st.bin_path is None
        assert "no verified runtime asset" in st.detail


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
        monkeypatch.setenv("HERMES_RUNTIME_DEV_BUILD", "1")
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=absent), \
             mock_patch.object(rm, "_install_from_release", return_value="no gh"), \
             mock_patch.object(rm, "_install_from_pinned_url", return_value="no pinned url"), \
             mock_patch.object(rm, "_install_from_sibling", return_value="no cargo"):
            st = rm.ensure_runtime(install=True)
        assert not st.satisfied
        assert "no gh" in st.detail and "no pinned url" in st.detail and "no cargo" in st.detail

    def test_sibling_build_is_not_a_stable_fallback(self, tmp_path, monkeypatch):
        _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "simplicio-home"))
        absent = rm.RuntimeStatus(None, "absent", None, "3.4.0", False)
        with mock_patch.object(rm, "runtime_status", return_value=absent), \
             mock_patch.object(rm, "_install_from_release", return_value="no gh"), \
             mock_patch.object(rm, "_install_from_pinned_url", return_value="no pinned url"), \
             mock_patch.object(rm, "_install_from_sibling") as sibling:
            st = rm.ensure_runtime(install=True)
        assert not st.satisfied
        sibling.assert_not_called()
        assert "developer sibling build disabled" in st.detail

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
            "schema": "runtime-lock/v2",
            "kernel": "simplicio",
            "min_version": "3.5.2",
            "assets": {
                self._ASSET_KEY: {
                    **entry,
                    "version": "3.5.2",
                    "url": "https://example.invalid/releases/download/v3.5.2/simplicio-bin",
                    "size": 21,
                    "target": {"os": "testsys", "arch": "testarch"},
                }
            },
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
            Path(cmd[out_idx]).write_bytes(b"x" * 21)
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

    def test_pinned_url_download_verifies_and_installs(self, tmp_path):
        payload = b"the-real-binary-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        lock = self._lock(sha256=digest)
        dest = tmp_path / "simplicio"

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size):
                nonlocal payload
                value, payload = payload, b""
                return value

        p1, p2 = self._patched_platform()
        with p1, p2, mock_patch.object(rm, "urlopen", return_value=Response()):
            err = rm._install_from_pinned_url(lock, dest)

        assert err is None
        assert dest.read_bytes() == b"the-real-binary-bytes"
        assert list(tmp_path.glob(".simplicio.url-download.*")) == []

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



class TestCanonicalSymlink:
    """Tests for the canonical PATH shim (issue #96): ``~/.local/bin/simplicio``
    (or ``$HERMES_CANONICAL_BIN_DIR`` override) must resolve and execute
    deterministically, mirroring what ``command -v simplicio`` and
    ``simplicio version`` show a human in a fresh shell -- and the repair
    must be idempotent (safe to run any number of times).
    """

    def _canonical_dir(self, tmp_path, monkeypatch):
        canon_dir = tmp_path / "canonical-bin"
        monkeypatch.setenv("HERMES_CANONICAL_BIN_DIR", str(canon_dir))
        return canon_dir

    def test_canonical_bin_dir_honors_override(self, tmp_path, monkeypatch):
        canon_dir = self._canonical_dir(tmp_path, monkeypatch)
        assert rm.canonical_bin_dir() == canon_dir

    def test_canonical_bin_dir_defaults_to_home_local_bin(self, monkeypatch):
        monkeypatch.delenv("HERMES_CANONICAL_BIN_DIR", raising=False)
        assert rm.canonical_bin_dir() == Path.home() / ".local" / "bin"

    def test_sync_creates_symlink_to_resolved_kernel(self, tmp_path, monkeypatch):
        _require_symlink_support(tmp_path)
        self._canonical_dir(tmp_path, monkeypatch)
        stub = _fake_managed_kernel(tmp_path, monkeypatch)
        lock = _write_lock(tmp_path, monkeypatch)

        # Isolate from whatever `simplicio` may genuinely be on this
        # machine's PATH -- resolution must fall through to the managed
        # dir stub, not a real PATH hit, for this test to be meaningful.
        with mock_patch("shutil.which", return_value=None):
            status = rm.runtime_status(lock)
        assert status.present
        assert status.source == "managed"

        err = rm.sync_canonical_symlink(status, lock)
        assert err is None

        link = rm.canonical_symlink_path(lock)
        assert link.is_symlink()
        assert link.resolve() == stub.resolve()
        if sys.platform != "win32":
            # The shim actually executes -- the #96 failure mode was a shim
            # whose target no longer existed.
            assert subprocess.run([str(link), "version"], capture_output=True).returncode in (0, 1)

    def test_sync_is_idempotent(self, tmp_path, monkeypatch):
        """Re-running sync against an already-correct shim is a no-op, and
        never raises or duplicates work -- required by issue #96's
        "reparo do binário é idempotente" acceptance criterion."""
        _require_symlink_support(tmp_path)
        self._canonical_dir(tmp_path, monkeypatch)
        _fake_managed_kernel(tmp_path, monkeypatch)
        lock = _write_lock(tmp_path, monkeypatch)
        with mock_patch("shutil.which", return_value=None):
            status = rm.runtime_status(lock)

        assert rm.sync_canonical_symlink(status, lock) is None
        link = rm.canonical_symlink_path(lock)
        first_target = os.readlink(link)

        # Second run: still None (no-op), same target, no exception.
        assert rm.sync_canonical_symlink(status, lock) is None
        assert os.readlink(link) == first_target

    def test_sync_repairs_dangling_symlink(self, tmp_path, monkeypatch):
        """The literal bug reported in #96: the shim is a symlink pointing
        at a target that no longer exists. sync_canonical_symlink must
        re-point it at a currently-resolvable kernel rather than leaving
        the dangling link in place."""
        _require_symlink_support(tmp_path)
        canon_dir = self._canonical_dir(tmp_path, monkeypatch)
        stub = _fake_managed_kernel(tmp_path, monkeypatch)
        lock = _write_lock(tmp_path, monkeypatch)

        canon_dir.mkdir(parents=True, exist_ok=True)
        link = rm.canonical_symlink_path(lock)
        link.symlink_to(tmp_path / "does-not-exist" / "simplicio")
        assert link.is_symlink() and not link.exists()  # dangling, by construction

        with mock_patch("shutil.which", return_value=None):
            status = rm.runtime_status(lock)
        err = rm.sync_canonical_symlink(status, lock)
        assert err is None
        assert link.exists()
        assert link.resolve() == stub.resolve()

    def test_sync_is_noop_without_resolved_kernel(self, tmp_path, monkeypatch):
        self._canonical_dir(tmp_path, monkeypatch)
        lock = _write_lock(tmp_path, monkeypatch)
        monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "nowhere"))
        with mock_patch("shutil.which", return_value=None):
            status = rm.runtime_status(lock)
        assert not status.present
        assert rm.sync_canonical_symlink(status, lock) is None

    def test_sync_refuses_to_clobber_real_file(self, tmp_path, monkeypatch):
        """A real (non-symlink) file at the canonical path is never
        overwritten -- only a missing path or an existing symlink is safe
        to touch, mirroring the "never overwrite a user-managed install"
        rule ``ensure_runtime`` already applies to the managed dir."""
        canon_dir = self._canonical_dir(tmp_path, monkeypatch)
        _fake_managed_kernel(tmp_path, monkeypatch)
        lock = _write_lock(tmp_path, monkeypatch)

        canon_dir.mkdir(parents=True, exist_ok=True)
        real_file = rm.canonical_symlink_path(lock)
        if sys.platform == "win32":
            real_file.write_bytes(b"not-a-symlink\r\n")
        else:
            real_file.write_text("#!/bin/sh\necho not-a-symlink\n", encoding="utf-8")
            real_file.chmod(0o755)

        with mock_patch("shutil.which", return_value=None):
            status = rm.runtime_status(lock)
        err = rm.sync_canonical_symlink(status, lock)
        assert err is not None
        assert "refusing" in err
        # Untouched.
        if sys.platform == "win32":
            assert real_file.read_bytes() == b"not-a-symlink\r\n"
        else:
            assert real_file.read_text(encoding="utf-8") == "#!/bin/sh\necho not-a-symlink\n"


# =========================================================================
# real (non-mocked) binary integration -- DOD.md Layer 2 / hub issue #579,
# #488: this repo's own handshake contract must be exercised against a real
# `simplicio` binary when one is reachable, not only against synthetic
# subprocess.CompletedProcess stand-ins. Skips cleanly (never fakes a pass)
# when no real binary is on PATH -- most CI/sandbox environments won't have
# one, dev machines with the managed install will.
# =========================================================================

class TestRealRuntimeBinary:
    def test_kernel_version_parses_a_real_installed_binary(self):
        real_bin = shutil.which("simplicio")
        if not real_bin:
            pytest.skip("no real 'simplicio' binary on PATH -- nothing to verify against")

        version = rm.kernel_version(real_bin)

        assert version is not None, (
            f"real binary at {real_bin} did not produce a version kernel_version() "
            "could parse -- banner format may have drifted"
        )
        assert rm.parse_semver(version) is not None, (
            f"kernel_version() returned {version!r}, which is not itself valid semver"
        )

    def test_resolve_kernel_finds_the_same_real_binary_unmocked(self, tmp_path, monkeypatch):
        real_bin = shutil.which("simplicio")
        if not real_bin:
            pytest.skip("no real 'simplicio' binary on PATH -- nothing to verify against")

        lock = _write_lock(tmp_path, monkeypatch)
        # No shutil.which mock here -- this is the real resolution order
        # running against the real environment, not a stand-in.
        path, source = rm.resolve_kernel(lock)

        assert path is not None
        assert source in ("env", "path", "managed")
