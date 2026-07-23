from __future__ import annotations

import json
from threading import Lock

from agent.local_agent_loop import LocalAgentLoop, receipt_json
from agent.prompt_zones import PromptZones
from tools.tool_call_batch import SafetyClass, ToolSpec


class FakeRuntime:
    def __init__(self) -> None:
        self.acquires: list[tuple[str, str, int]] = []
        self.releases: list[str] = []

    def acquire(self, session_id: str, prefix_sha256: str, generation: int):
        self.acquires.append((session_id, prefix_sha256, generation))
        return {"lease_id": f"lease-{len(self.acquires)}"}

    def release(self, lease_id: str) -> None:
        self.releases.append(lease_id)


def test_local_loop_reuses_lease_and_reports_parallel_read_receipt() -> None:
    runtime = FakeRuntime()
    calls: list[str] = []
    lock = Lock()
    registry = {
        "read_a": ToolSpec("read_a", SafetyClass.READ_ONLY),
        "read_b": ToolSpec("read_b", SafetyClass.READ_ONLY),
    }

    def handler(call):
        with lock:
            calls.append(call.name)
        return {"name": call.name}

    with LocalAgentLoop("session-1", PromptZones({"system": "stable"}), runtime, registry) as loop:
        payload = json.dumps([
            {"id": "a", "tool": "read_a", "args": {}},
            {"id": "b", "tool": "read_b", "args": {}},
        ])
        first = loop.run_turn(payload, handler)
        second = loop.run_turn(payload, handler)

        assert first.receipt.parallel is True
        assert first.receipt.ok is True
        assert first.receipt.call_ids == ("a", "b")
        assert first.receipt.prefix_sha256 == second.receipt.prefix_sha256
        assert first.receipt.lease_id == second.receipt.lease_id
        assert len(runtime.acquires) == 1
        assert sorted(calls) == ["read_a", "read_a", "read_b", "read_b"]
        assert json.loads(receipt_json(first)) == first.receipt.to_dict()

    assert runtime.releases == ["lease-1"]
