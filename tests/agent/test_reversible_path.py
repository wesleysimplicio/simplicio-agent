from pathlib import Path

from agent import reversible_path
from agent.reversible_path import (
    BASELINE_CONTENT,
    FINAL_CONTENT,
    prepare_reversible_workspace,
    run_local_reversible_path,
)
from tools.checkpoint_manager import CheckpointManager
from tools.simplicio_transport import TransportError, TransportReceipt


class FakeTransport:
    def __init__(self, *, gate_ok=True, decision=None):
        self.gate_ok = gate_ok
        self.decision = decision

    def gate(self, *args, **kwargs):
        if self.gate_ok:
            value = {"decision": self.decision} if self.decision else {"allowed": True}
            return TransportReceipt.success("gate", value, request_id="gate-181")
        return TransportReceipt.failure(
            "gate",
            TransportError("denied", "runtime gate unavailable"),
            request_id="gate-181",
        )

    def checkpoint(self, *args, **kwargs):
        return TransportReceipt.success(
            "checkpoint", {"recorded": True}, request_id="checkpoint-181"
        )

    def health(self):
        return {"status": "healthy" if self.gate_ok else "unavailable"}


def _manager(root: Path) -> CheckpointManager:
    return CheckpointManager(enabled=True, checkpoint_base=root / ".checkpoints")


class _CheckpointDouble:
    def __init__(self, *, restore_success=True):
        self.restore_success = restore_success

    def new_turn(self):
        return None

    def ensure_checkpoint(self, working_dir, reason):
        return True

    def list_checkpoints(self, working_dir):
        return [{"hash": "a" * 40, "short_hash": "aaaaaaa"}]

    def restore(self, working_dir, commit_hash, file_path):
        return {"success": self.restore_success}


def test_local_reversible_path_proves_after_and_undo(tmp_path):
    prepare_reversible_workspace(tmp_path)

    result = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(),
        checkpoint_manager=_manager(tmp_path),
    )

    assert result.status == "completed_verified"
    assert result.before["content"] == BASELINE_CONTENT
    assert result.after["content"] == FINAL_CONTENT
    assert result.before["sha256"] != result.after["sha256"]
    assert result.before["sha256"] == result.undo["sha256"]
    assert result.watcher["status"] == "passed"
    assert result.goal["state"] == "completed_verified"
    assert result.delivery_certificate["status"] == "passed"
    assert result.availability["desktop_uia"]["available"] is False
    assert result.to_dict()["trace"][-1]["stage"] == "delivery"


def test_action_identity_is_stable_across_reexecution(tmp_path):
    prepare_reversible_workspace(tmp_path)
    first = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(),
        checkpoint_manager=_manager(tmp_path),
    )
    second = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(),
        checkpoint_manager=_manager(tmp_path),
    )

    assert first.action_digest == second.action_digest
    assert first.idempotency_key == second.idempotency_key
    assert second.undo["content"] == BASELINE_CONTENT


def test_runtime_gate_failure_is_explicit_and_does_not_mutate(tmp_path):
    prepare_reversible_workspace(tmp_path)
    result = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(gate_ok=False),
        checkpoint_manager=_manager(tmp_path),
    )

    assert result.status == "blocked"
    assert result.availability["runtime"]["available"] is False
    assert result.availability["desktop_uia"]["available"] is False
    assert (
        tmp_path / "controlled-artifact" / "requirements.txt"
    ).read_text() == BASELINE_CONTENT
    assert result.after["sha256"] == result.before["sha256"]


def test_runtime_confirmation_is_not_treated_as_allow(tmp_path):
    prepare_reversible_workspace(tmp_path)
    result = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(decision="confirm"),
        checkpoint_manager=_manager(tmp_path),
    )

    assert result.status == "blocked"
    assert result.availability["runtime"]["available"] is False
    assert result.before["content"] == BASELINE_CONTENT


def test_failed_observation_is_blocked_without_verified_completion(tmp_path, monkeypatch):
    prepare_reversible_workspace(tmp_path)
    original_write_text = Path.write_text

    def write_wrong_content(path, data, *args, **kwargs):
        if data == FINAL_CONTENT:
            data = "# unexpected observation\n"
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(reversible_path.Path, "write_text", write_wrong_content)
    result = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(),
        checkpoint_manager=_CheckpointDouble(),
    )

    assert result.status == "blocked"
    assert "observation failed" in result.goal["facts"][-1]["text"]
    assert result.delivery_certificate["status"] == "blocked"


def test_failed_restore_is_blocked_without_verified_completion(tmp_path):
    prepare_reversible_workspace(tmp_path)
    result = run_local_reversible_path(
        tmp_path,
        transport=FakeTransport(),
        checkpoint_manager=_CheckpointDouble(restore_success=False),
    )

    assert result.status == "blocked"
    assert "restore failed" in result.goal["facts"][-1]["text"]
    assert result.delivery_certificate["status"] == "blocked"
