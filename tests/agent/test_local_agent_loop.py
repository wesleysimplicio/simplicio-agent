from __future__ import annotations

import json
from threading import Lock

from agent.local_agent_loop import LocalAgentLoop, receipt_json
from agent.no_progress_guard import GuardPolicy, NoProgressGuard
from agent.prompt_zones import PromptZones
from agent.schema_tiering import build_schema_tier_catalog
from tools.browser_interaction_contract import BrowserStateRegistry
from tools.registry import ToolRegistry
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


def test_local_loop_reuses_lease_and_reports_parallel_read_receipt(tmp_path) -> None:
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

    with LocalAgentLoop(
        "session-1",
        PromptZones({"system": "stable"}),
        runtime,
        registry,
        receipt_directory=tmp_path,
    ) as loop:
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


def test_local_loop_end_to_end_composes_loop_primitives(tmp_path) -> None:
    runtime = FakeRuntime()
    browser = BrowserStateRegistry()
    browser_state = browser.capture(
        "session-e2e",
        '- button "Send" [ref=e2]\n- textbox "Password" [ref=e1]',
        {
            "e2": {"role": "button", "name": "Send"},
            "e1": {"role": "textbox", "name": "Password"},
        },
    )
    registry = {
        "read_a": ToolSpec("read_a", SafetyClass.READ_ONLY),
        "read_b": ToolSpec("read_b", SafetyClass.READ_ONLY),
        "write": ToolSpec("write", SafetyClass.MUTATION),
    }
    schema_registry = ToolRegistry()
    for name in registry:
        schema_registry.register(
            name=name,
            toolset="e2e",
            schema={
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda _args: "ok",
        )
    schema_catalog = build_schema_tier_catalog(
        schema_registry,
        core_tool_names=("read_a",),
        full_tier_limit=1,
        max_expansions=4,
    )
    guard = NoProgressGuard(
        GuardPolicy(
            warning_threshold=1, veto_threshold=2, hard_threshold=3, replan_threshold=1
        )
    )
    seen_evaluations = []
    calls = []

    def handler(call):
        calls.append(call.name)
        if call.name == "read_a":
            return {"compact_state": browser_state}
        return {"status": "unchanged"}

    with LocalAgentLoop(
        "session-e2e",
        PromptZones({"system": "stable"}),
        runtime,
        registry,
        schema_catalog=schema_catalog,
        no_progress_guard=guard,
        receipt_directory=tmp_path,
        evaluation_hook=seen_evaluations.append,
    ) as loop:
        reads = loop.run_turn(
            json.dumps([
                {"id": "a", "tool": "read_a", "args": {}},
                {"id": "b", "tool": "read_b", "args": {}},
            ]),
            handler,
        )
        mutation_payload = json.dumps([{"id": "w", "tool": "write", "args": {}}])
        first_write = loop.run_turn(mutation_payload, handler)
        second_write = loop.run_turn(mutation_payload, handler)
        blocked_write = loop.run_turn(mutation_payload, handler)

    assert reads.receipt.parallel is True
    assert reads.receipt.browser_state == browser_state
    assert reads.receipt.grammar_sha256
    assert reads.receipt.schema_prefix_sha256
    assert reads.receipt.schema_expansions
    assert first_write.receipt.parallel is False
    assert first_write.receipt.ok is True
    assert second_write.receipt.recovery is None
    assert blocked_write.receipt.recovery == "replan"
    assert blocked_write.results[0].error == "no_progress:replan"
    assert calls.count("write") == 2
    assert len(seen_evaluations) == 4
    assert all(item["receipt"]["receipt_sha"] for item in seen_evaluations)
    assert len(list(tmp_path.glob("*.json"))) == 3
