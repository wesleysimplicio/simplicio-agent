"""Tests for the $ref dependency detector and DAG dispatch routing
(issue #115): ``agent.tool_executor.detect_tool_call_dag`` and
``execute_tool_calls_dag``, plus the real routing decision wired into
``AIAgent._execute_tool_calls``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.tool_executor import detect_tool_call_dag, execute_tool_calls_dag


def _tc(call_id: str, name: str, args: dict):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


class TestDetectToolCallDag:
    def test_independent_batch_returns_none(self):
        calls = [_tc("a", "read_file", {"path": "x"}), _tc("b", "read_file", {"path": "y"})]
        assert detect_tool_call_dag(calls) is None

    def test_single_call_returns_none(self):
        assert detect_tool_call_dag([_tc("a", "read_file", {"path": "x"})]) is None

    def test_string_ref_to_batch_member_detected(self):
        calls = [_tc("a", "search", {"q": "x"}), _tc("b", "summarize", {"input": "$ref:a"})]
        nodes = detect_tool_call_dag(calls)
        assert nodes is not None
        by_id = {n.node_id: n for n in nodes}
        assert by_id["b"].depends_on == ("a",)
        assert by_id["a"].depends_on == ()

    def test_dict_ref_to_batch_member_detected(self):
        calls = [_tc("a", "search", {"q": "x"}), _tc("b", "summarize", {"input": {"$ref": "a"}})]
        nodes = detect_tool_call_dag(calls)
        assert nodes is not None
        by_id = {n.node_id: n for n in nodes}
        assert by_id["b"].depends_on == ("a",)

    def test_nested_ref_inside_list_detected(self):
        calls = [
            _tc("a", "search", {"q": "x"}),
            _tc("b", "combine", {"items": [{"$ref": "a"}, "literal"]}),
        ]
        nodes = detect_tool_call_dag(calls)
        assert nodes is not None
        by_id = {n.node_id: n for n in nodes}
        assert by_id["b"].depends_on == ("a",)

    def test_ref_to_id_outside_batch_is_not_a_detected_dag(self):
        """A $ref to something that isn't another member of THIS batch can
        never resolve (nothing in outputs would satisfy it) — must fall
        back to the existing independent-batch path, not route to a DAG
        that would immediately fail."""
        calls = [_tc("a", "process", {"input": "$ref:some-other-turns-call-id"})]
        assert detect_tool_call_dag(calls) is None

    def test_malformed_json_args_treated_as_no_deps(self):
        bad_call = SimpleNamespace(
            id="a", type="function", function=SimpleNamespace(name="x", arguments="not json")
        )
        good_call = _tc("b", "y", {"z": 1})
        assert detect_tool_call_dag([bad_call, good_call]) is None


class TestExecuteToolCallsDag:
    def test_appends_results_in_original_tool_call_order(self):
        calls = [_tc("a", "search", {"q": "x"}), _tc("b", "summarize", {"input": "$ref:a"})]

        def _invoke_tool(function_name, function_args, effective_task_id, *_, **__):
            if function_name == "search":
                return "search-result"
            return f"summary-of:{function_args.get('input')}"

        agent = SimpleNamespace(_invoke_tool=_invoke_tool, _latency_probe=None)
        messages: list = []

        with patch("agent.tool_executor._flush_session_db_after_tool_progress"):
            execute_tool_calls_dag(agent, SimpleNamespace(tool_calls=calls), messages, "task-1")

        assert len(messages) == 2
        assert messages[0]["tool_call_id"] == "a"
        assert messages[0]["content"] == "search-result"
        assert messages[1]["tool_call_id"] == "b"
        assert messages[1]["content"] == "summary-of:search-result"

    def test_error_in_upstream_node_produces_honest_error_not_fabricated_success(self):
        calls = [_tc("a", "flaky", {}), _tc("b", "consume", {"input": "$ref:a"})]

        def _invoke_tool(function_name, function_args, effective_task_id, *_, **__):
            if function_name == "flaky":
                raise RuntimeError("upstream boom")
            return "should never run"

        agent = SimpleNamespace(_invoke_tool=_invoke_tool, _latency_probe=None)
        messages: list = []

        with patch("agent.tool_executor._flush_session_db_after_tool_progress"):
            execute_tool_calls_dag(agent, SimpleNamespace(tool_calls=calls), messages, "task-1")

        assert len(messages) == 2
        # Node 'a' really failed.
        assert "error" in messages[0]["content"].lower()
        assert "upstream boom" in messages[0]["content"]
        # Node 'b' never ran (its dependency failed) — must be an honest
        # error, not the literal string its (never-invoked) tool would have
        # returned.
        assert "error" in messages[1]["content"].lower()
        assert "should never run" not in messages[1]["content"]

    def test_independent_nodes_in_dag_batch_both_still_run(self):
        """A batch can have SOME dependent pairs and some fully-independent
        nodes in the same DAG — both must execute and report real results."""
        calls = [
            _tc("a", "search", {"q": "x"}),
            _tc("b", "summarize", {"input": "$ref:a"}),
            _tc("c", "unrelated", {"q": "y"}),
        ]

        def _invoke_tool(function_name, function_args, effective_task_id, *_, **__):
            return f"{function_name}-ran"

        agent = SimpleNamespace(_invoke_tool=_invoke_tool, _latency_probe=None)
        messages: list = []

        with patch("agent.tool_executor._flush_session_db_after_tool_progress"):
            execute_tool_calls_dag(agent, SimpleNamespace(tool_calls=calls), messages, "task-1")

        contents = {m["tool_call_id"]: m["content"] for m in messages}
        assert contents["a"] == "search-ran"
        assert contents["b"] == "summarize-ran"
        assert contents["c"] == "unrelated-ran"


class TestTimeoutGuard:
    def test_hung_node_times_out_with_honest_error_not_hanging_the_turn(self, monkeypatch):
        """Mirrors tests/tools/test_tool_timeout.py's contract for the
        concurrent path: a stuck tool call must not hold the DAG (and the
        turn) hostage past the configured timeout guard."""
        import time as _time

        import agent.tool_executor as te

        monkeypatch.setattr(te, "_CONCURRENT_TOOL_TIMEOUT", 0.05)

        def _invoke_tool(function_name, function_args, effective_task_id, *_, **__):
            if function_name == "hangs":
                _time.sleep(5.0)  # never actually waited out — guard fires first
            return "fast-result"

        calls = [_tc("a", "hangs", {}), _tc("b", "consume", {"input": "$ref:a"})]
        agent = SimpleNamespace(_invoke_tool=_invoke_tool, _latency_probe=None)
        messages: list = []

        t0 = _time.monotonic()
        with patch("agent.tool_executor._flush_session_db_after_tool_progress"):
            execute_tool_calls_dag(agent, SimpleNamespace(tool_calls=calls), messages, "task-1")
        elapsed = _time.monotonic() - t0

        assert elapsed < 2.0, f"timeout guard did not fire promptly, waited {elapsed:.2f}s"
        assert len(messages) == 2
        for msg in messages:
            content = msg["content"].lower()
            assert "error" in content
            assert "timeout" in content or "timed out" in content


class TestRoutingIntegration:
    """Confirms the real dispatch decision in AIAgent._execute_tool_calls:
    a batch with detected $ref dependencies routes to the DAG path; a
    batch without them is completely unaffected (routes exactly as before,
    same latency profile — no new overhead on the hot independent-batch
    path beyond one cheap, deterministic detection pass)."""

    def test_dependent_batch_routes_to_dag_path(self):
        with patch("run_agent.AIAgent._execute_tool_calls_dag_check_stub", create=True):
            pass  # placeholder to keep patch context managers balanced if extended later

        import run_agent

        calls = [_tc("a", "search", {"q": "x"}), _tc("b", "summarize", {"input": "$ref:a"})]
        assistant_message = SimpleNamespace(tool_calls=calls)

        dag_called = {"count": 0}
        sequential_called = {"count": 0}
        concurrent_called = {"count": 0}

        class _FakeAgent:
            _executing_tools = False

            def _execute_tool_calls(self, *a, **k):
                return run_agent.AIAgent._execute_tool_calls(self, *a, **k)

            def _execute_tool_calls_sequential(self, *a, **k):
                sequential_called["count"] += 1

            def _execute_tool_calls_concurrent(self, *a, **k):
                concurrent_called["count"] += 1

        with patch(
            "agent.tool_executor.execute_tool_calls_dag",
            side_effect=lambda *a, **k: dag_called.__setitem__("count", dag_called["count"] + 1),
        ):
            _FakeAgent()._execute_tool_calls(assistant_message, [], "task-1")

        assert dag_called["count"] == 1
        assert sequential_called["count"] == 0
        assert concurrent_called["count"] == 0

    def test_independent_batch_does_not_route_to_dag_path(self):
        import run_agent

        calls = [_tc("a", "read_file", {"path": "x"}), _tc("b", "read_file", {"path": "y"})]
        assistant_message = SimpleNamespace(tool_calls=calls)

        dag_called = {"count": 0}
        concurrent_called = {"count": 0}

        class _FakeAgent:
            _executing_tools = False

            def _execute_tool_calls(self, *a, **k):
                return run_agent.AIAgent._execute_tool_calls(self, *a, **k)

            def _execute_tool_calls_sequential(self, *a, **k):
                pass

            def _execute_tool_calls_concurrent(self, *a, **k):
                concurrent_called["count"] += 1

        with (
            patch(
                "agent.tool_executor.execute_tool_calls_dag",
                side_effect=lambda *a, **k: dag_called.__setitem__("count", dag_called["count"] + 1),
            ),
            patch("run_agent._should_parallelize_tool_batch", return_value=True),
        ):
            _FakeAgent()._execute_tool_calls(assistant_message, [], "task-1")

        assert dag_called["count"] == 0
        assert concurrent_called["count"] == 1
