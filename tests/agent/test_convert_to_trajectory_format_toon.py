"""convert_to_trajectory_format understands TOON tool results (issue #16).

TOON-encoded structured tool results don't start with ``{``/``[``, so the
existing "looks like JSON" gate never even tries to parse them — this
covers the added TOON fallback branch, gated on the session's pinned
``_toon_prompts_enabled`` flag so a plain-text tool result never gets
misclassified as a spurious dict when the flag is off (the common case).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent.agent_runtime_helpers import convert_to_trajectory_format
from agent.toon_codec import to_toon


def _agent(toon_enabled: bool):
    return SimpleNamespace(
        _toon_prompts_enabled=toon_enabled,
        _format_tools_for_system_message=lambda: "[]",
    )


def _messages_with_tool_result(content: str):
    return [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "write_file", "arguments": '{"path": "a.py"}'}}
            ],
        },
        {"role": "tool", "content": content, "tool_call_id": "call_1"},
    ]


def test_json_tool_result_still_parsed_as_dict():
    agent = _agent(toon_enabled=False)
    messages = _messages_with_tool_result(json.dumps({"success": True, "bytes_written": 3}))
    trajectory = convert_to_trajectory_format(agent, messages, "do it", completed=True)
    tool_entry = next(t for t in trajectory if t["from"] == "tool")
    assert '"success": true' in tool_entry["value"]


def test_toon_tool_result_decoded_when_flag_enabled():
    agent = _agent(toon_enabled=True)
    encoded = to_toon({"success": True, "bytes_written": 3})
    messages = _messages_with_tool_result(encoded)
    trajectory = convert_to_trajectory_format(agent, messages, "do it", completed=True)
    tool_entry = next(t for t in trajectory if t["from"] == "tool")
    # Decoded into a real object embedded in the <tool_response> JSON, not
    # left as a raw TOON string blob.
    assert '"success": true' in tool_entry["value"]
    assert '"bytes_written": 3' in tool_entry["value"]


def test_toon_looking_text_left_as_string_when_flag_disabled():
    """Same TOON text, but the session never had toon_prompts on -- must
    NOT be speculatively decoded (avoids misclassifying plain text that
    happens to contain a colon)."""
    agent = _agent(toon_enabled=False)
    encoded = to_toon({"success": True, "bytes_written": 3})
    messages = _messages_with_tool_result(encoded)
    trajectory = convert_to_trajectory_format(agent, messages, "do it", completed=True)
    tool_entry = next(t for t in trajectory if t["from"] == "tool")
    # Left as the raw TOON string, not decoded into a nested object.
    inner = tool_entry["value"].removeprefix("<tool_response>\n").removesuffix("\n</tool_response>")
    parsed = json.loads(inner)
    assert parsed["content"] == encoded


def test_plain_text_error_not_misparsed_even_with_flag_on():
    agent = _agent(toon_enabled=True)
    messages = _messages_with_tool_result("Error executing tool 'write_file': disk full")
    # Must not raise, and the trajectory conversion completes.
    trajectory = convert_to_trajectory_format(agent, messages, "do it", completed=True)
    assert any(t["from"] == "human" for t in trajectory)
