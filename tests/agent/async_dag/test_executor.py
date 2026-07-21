"""Tests for ``agent.async_dag.executor`` (Proposta C)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent.async_dag import DagExecutor, DagNode, build_dag
from agent.async_dag.executor import DagError


async def _dispatch(tool: str, args):
    if tool == "fail":
        raise RuntimeError("boom")
    return {"tool": tool, "args": dict(args)}


def test_build_dag_simple_chain() -> None:
    nodes = [
        DagNode("a", "echo"),
        DagNode("b", "echo", args={"x": "$ref:a"}, depends_on=("a",)),
        DagNode("c", "echo", args={"y": "$ref:b"}, depends_on=("b",)),
    ]
    levels = build_dag(nodes)
    assert levels == [["a"], ["b"], ["c"]]


def test_build_dag_fans_out_and_in() -> None:
    nodes = [
        DagNode("a", "echo"),
        DagNode("b", "echo", depends_on=("a",)),
        DagNode("c", "echo", depends_on=("a",)),
        DagNode("d", "echo", depends_on=("b", "c")),
    ]
    levels = build_dag(nodes)
    assert levels[0] == ["a"]
    assert set(levels[1]) == {"b", "c"}
    assert levels[2] == ["d"]


def test_cycle_raises() -> None:
    nodes = [
        DagNode("a", "echo", depends_on=("b",)),
        DagNode("b", "echo", depends_on=("a",)),
    ]
    with pytest.raises(DagError):
        build_dag(nodes)


def test_unknown_dep_raises() -> None:
    nodes = [DagNode("a", "echo", depends_on=("zzz",))]
    with pytest.raises(DagError):
        build_dag(nodes)


def test_executor_runs_topologically() -> None:
    nodes = [
        DagNode("a", "alpha"),
        DagNode("b", "beta", args={"x": "$ref:a"}, depends_on=("a",)),
    ]
    ex = DagExecutor(dispatch=_dispatch)
    result = asyncio.run(ex.run(nodes))
    assert result.ok
    assert result.outputs["a"]["tool"] == "alpha"
    assert result.outputs["b"]["args"]["x"] == result.outputs["a"]


def test_executor_runs_level_in_parallel() -> None:
    timings: list[tuple[str, float]] = []

    async def slow(tool: str, args):
        await asyncio.sleep(0.05)
        timings.append((tool, asyncio.get_event_loop().time()))
        return tool

    ex = DagExecutor(dispatch=slow)
    nodes = [DagNode(f"n{i}", f"t{i}") for i in range(4)]
    result = asyncio.run(ex.run(nodes))
    assert result.ok
    # 4 parallel nodes each 50 ms should finish in well under 200 ms
    assert result.elapsed_s < 0.18


def test_failed_node_short_circuits_dependents() -> None:
    nodes = [
        DagNode("a", "fail"),
        DagNode("b", "echo", depends_on=("a",)),
    ]
    ex = DagExecutor(dispatch=_dispatch)
    result = asyncio.run(ex.run(nodes))
    assert not result.ok
    assert "a" in result.errors
    assert "b" in result.errors
    assert "upstream dep failed" in repr(result.errors["b"])


def test_executor_queues_adversarial_stream_under_resident_cap() -> None:
    active = 0
    peak = 0

    async def tracked(tool: str, args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return tool

    ex = DagExecutor(dispatch=tracked, max_concurrency=16, max_resident=2)
    result = asyncio.run(ex.run([DagNode(f"n{i}", "work") for i in range(12)]))

    assert result.ok
    assert peak == 2
    assert result.peak_resident == 2
    assert result.max_resident == 2


def test_executor_rejects_nodes_at_recursion_limit() -> None:
    ex = DagExecutor(dispatch=_dispatch, max_depth=2)
    result = asyncio.run(ex.run([DagNode("deep", "echo", depth=2)]))

    assert not result.ok
    assert "deep" in result.errors
    assert "recursion depth" in str(result.errors["deep"])


def test_executor_enforces_strictly_shrinking_summary() -> None:
    source = "context " * 100

    async def summarize(tool: str, args):
        return {"summary": args["summary"]}

    ex = DagExecutor(dispatch=summarize)
    passing = asyncio.run(
        ex.run([
            DagNode(
                "summary",
                "summarize",
                args={"summary": "context " * 20},
                input_context=source,
            )
        ])
    )
    failing = asyncio.run(
        ex.run([
            DagNode(
                "summary",
                "summarize",
                args={"summary": source},
                input_context=source,
            )
        ])
    )

    assert passing.ok
    assert not failing.ok
    assert "strictly shrink" in str(failing.errors["summary"])


def test_executor_emits_tuple_identity_and_real_receipt(tmp_path: Path) -> None:
    node = DagNode(
        "read", "read_file", args={"path": "README.md"}, yool_id="agent.room"
    )
    ex = DagExecutor(dispatch=_dispatch, receipt_directory=tmp_path)
    result = asyncio.run(ex.run([node]))

    assert result.ok
    receipt = result.receipts["read"]
    assert node.tuple_hash in receipt.meta["tuple_hash"]
    assert receipt.yool_id == "agent.room"
    assert receipt.cost.tokens > 0
    assert list(tmp_path.glob("*.json"))
