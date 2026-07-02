"""summarize_background_review_actions understands TOON tool results (issue #16).

The background-review fork inherits the parent's pinned context.toon_prompts
flag, so its own memory/skill_manage tool results may be TOON rather than
JSON. This covers the parse_tool_payload (JSON-then-TOON) fallback added to
agent/background_review.py.
"""

import json

from run_agent import AIAgent
from agent.toon_codec import to_toon


_summarize = AIAgent._summarize_background_review_actions


def _tool_msg(tool_call_id, raw_content):
    return {"role": "tool", "tool_call_id": tool_call_id, "content": raw_content}


def test_toon_encoded_success_result_is_surfaced():
    payload = {"success": True, "message": "Memory entry created."}
    encoded = to_toon(payload)
    review_messages = [_tool_msg("call_toon", encoded)]

    actions = _summarize(review_messages, prior_snapshot=[])

    assert actions == ["Memory entry created."]


def test_toon_encoded_failed_result_is_not_surfaced():
    payload = {"success": False, "message": "write failed"}
    encoded = to_toon(payload)
    review_messages = [_tool_msg("call_toon", encoded)]

    actions = _summarize(review_messages, prior_snapshot=[])

    assert actions == []


def test_mixed_json_and_toon_results_both_surface():
    json_payload = json.dumps({"success": True, "message": "Skill created."})
    toon_payload = to_toon({"success": True, "message": "Memory entry created."})
    review_messages = [
        _tool_msg("call_json", json_payload),
        _tool_msg("call_toon", toon_payload),
    ]

    actions = _summarize(review_messages, prior_snapshot=[])

    assert set(actions) == {"Skill created.", "Memory entry created."}
