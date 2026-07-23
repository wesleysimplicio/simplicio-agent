import json
import time

import pytest

from tools.tool_call_batch import (
    BatchValidationError,
    SafetyClass,
    ToolSpec,
    build_gbnf,
    execute_tool_call_batch,
    parse_tool_call_batch,
)


REGISTRY = {
    "read_file": ToolSpec("read_file", allowed_args=frozenset({"path"})),
    "write_file": ToolSpec(
        "write_file", SafetyClass.MUTATION, frozenset({"path", "content"}), frozenset({"path", "content"})
    ),
}


def test_parser_accepts_one_or_many_and_assigns_stable_ids():
    calls = parse_tool_call_batch('[{"tool":"read_file","args":{"path":"a"}},{"tool":"read_file","args":{"path":"b"}}]', REGISTRY)
    assert [call.call_id for call in calls] == ["0", "1"]


@pytest.mark.parametrize("payload", ["[]", "{\"tool\":\"read_file\"}", "[", "[1]"])
def test_invalid_syntax_and_empty_arrays_have_no_dispatch(payload):
    with pytest.raises(BatchValidationError):
        parse_tool_call_batch(payload, REGISTRY)


def test_unknown_tool_args_and_duplicate_ids_are_rejected():
    for payload in [
        '[{"tool":"missing","args":{}}]',
        '[{"tool":"read_file","args":{"path":"a","extra":1}}]',
        '[{"id":"x","tool":"read_file","args":{"path":"a"}},{"id":"x","tool":"read_file","args":{"path":"b"}}]',
    ]:
        with pytest.raises(BatchValidationError):
            parse_tool_call_batch(payload, REGISTRY)


def test_gbnf_is_deterministic_and_registry_bound():
    assert build_gbnf(REGISTRY) == build_gbnf(dict(reversed(list(REGISTRY.items()))))
    assert '"read_file" | "write_file"' in build_gbnf(REGISTRY)


def test_only_read_only_calls_parallelize_and_results_keep_input_order():
    started = []

    def handler(call):
        started.append(call.args["path"])
        time.sleep(0.01 if call.args["path"] == "a" else 0)
        return call.args["path"]

    results = execute_tool_call_batch(
        '[{"tool":"read_file","args":{"path":"a"}},{"tool":"read_file","args":{"path":"b"}}]',
        REGISTRY,
        handler,
    )
    assert [result.value for result in results] == ["a", "b"]
    assert sorted(started) == ["a", "b"]


def test_mutation_batch_is_sequential_and_handler_failure_is_classified():
    calls = []

    def handler(call):
        calls.append(call.name)
        raise RuntimeError("denied")

    payload = json.dumps([{"tool": "write_file", "args": {"path": "a", "content": "x"}}])
    results = execute_tool_call_batch(payload, REGISTRY, handler)
    assert calls == ["write_file"]
    assert results[0].ok is False
    assert results[0].error == "RuntimeError"
