"""Tests for ``agent.tool_executor.run_dag_tool_batch``.

Additive, opt-in wiring of ``agent.async_dag.DagExecutor`` into the tool
executor module: a caller with a genuine dependency chain between tool
calls (unlike ``execute_tool_calls_concurrent``, which assumes every call
in a batch is independent) can use this to run them with dependency-aware
scheduling. These tests exercise the new function in isolation with a
minimal fake agent — they do not touch ``execute_tool_calls_concurrent``
or ``execute_tool_calls_sequential``.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.async_dag import DagNode
from agent.tool_executor import run_dag_tool_batch


class _FakeAgent:
    """Minimal stand-in exposing only what ``run_dag_tool_batch`` needs."""

    def __init__(self, tool_impl):
        self._tool_impl = tool_impl
        self.calls: list[tuple[str, dict, str]] = []

    def _invoke_tool(self, function_name, function_args, effective_task_id, *_, **__):
        self.calls.append((function_name, dict(function_args), effective_task_id))
        return self._tool_impl(function_name, function_args)


def test_run_dag_tool_batch_resolves_dependency_output():
    def _tool_impl(name: str, args: dict):
        if name == "fail":
            raise RuntimeError("boom")
        return {"tool": name, "args": args}

    agent = _FakeAgent(_tool_impl)
    nodes = [
        DagNode("a", "alpha", args={"x": 1}),
        DagNode("b", "beta", args={"upstream": "$ref:a"}, depends_on=("a",)),
    ]

    result = asyncio.run(run_dag_tool_batch(agent, nodes, "task-1"))

    assert result.ok
    assert result.outputs["a"] == {"tool": "alpha", "args": {"x": 1}}
    assert result.outputs["b"]["args"]["upstream"] == result.outputs["a"]
    # Dispatch reached the real agent._invoke_tool for both nodes, in
    # topological order (a before b).
    assert [c[0] for c in agent.calls] == ["alpha", "beta"]
    assert agent.calls[0][2] == "task-1"


def test_run_dag_tool_batch_short_circuits_on_upstream_failure():
    def _tool_impl(name: str, args: dict):
        if name == "fail":
            raise RuntimeError("boom")
        return {"tool": name}

    agent = _FakeAgent(_tool_impl)
    nodes = [
        DagNode("a", "fail"),
        DagNode("b", "beta", depends_on=("a",)),
    ]

    result = asyncio.run(run_dag_tool_batch(agent, nodes, "task-1"))

    assert not result.ok
    assert "a" in result.errors
    assert "b" in result.errors
    # "b" was never dispatched to _invoke_tool because its dependency failed.
    assert [c[0] for c in agent.calls] == ["fail"]


def test_run_dag_tool_batch_runs_independent_nodes_concurrently():
    def _tool_impl(name: str, args: dict):
        return {"tool": name}

    agent = _FakeAgent(_tool_impl)
    nodes = [DagNode(f"n{i}", f"t{i}") for i in range(4)]

    result = asyncio.run(run_dag_tool_batch(agent, nodes, "task-1", max_concurrency=4))

    assert result.ok
    assert len(result.outputs) == 4
    assert result.levels == [[n.node_id for n in nodes]]
