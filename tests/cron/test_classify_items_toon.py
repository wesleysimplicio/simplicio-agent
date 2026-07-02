"""TOON rollout for cron/scripts/classify_items.py (issue #14/#16).

``_build_prompt`` batches item views into a single TOON table by default
(the "array uniforme por item" case named in #16) instead of one
``json.dumps`` line per item; ``--legacy-json-items`` restores the old
behavior for rollback/comparison. Both paths must preserve list *order*
so the classifier's ``index``-keyed response still maps back correctly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cron.scripts.classify_items import _build_prompt, _item_view, _parse_scores, _MAX_FIELD_CHARS


ITEMS = [
    {"title": "Server down", "url": "http://example.com/x", "id": "a1"},
    {"title": "Meeting reminder", "url": "http://example.com/y", "id": "b2"},
    {"title": "Newsletter", "url": "http://example.com/z", "id": "c3"},
]


def test_build_prompt_toon_default_contains_toon_table_header():
    prompt = _build_prompt(ITEMS, "urgent if server related")
    assert "ITEMS:" in prompt
    # TOON table header for a uniform array of {title,url} objects.
    assert "[3]{title,url}:" in prompt
    assert "Server down" in prompt
    assert "Meeting reminder" in prompt
    # The old per-item bracketed-index JSON lines are gone.
    assert '"title":' not in prompt


def test_build_prompt_legacy_json_items_matches_old_format():
    prompt = _build_prompt(ITEMS, "urgent if server related", legacy_json_items=True)
    assert '[0] {"title": "Server down"' in prompt
    assert '[1] {"title": "Meeting reminder"' in prompt
    assert '[2] {"title": "Newsletter"' in prompt


def test_toon_prompt_preserves_item_order_for_index_based_scoring():
    prompt = _build_prompt(ITEMS, "criteria")
    # All three titles present, in original order, as TOON table rows.
    lines = [l.strip() for l in prompt.splitlines() if l.strip().startswith(("Server", "Meeting", "News"))]
    assert [l.split(",", 1)[0] for l in lines] == ["Server down", "Meeting reminder", "Newsletter"]


def test_item_view_truncates_long_fields():
    long_text = "x" * (_MAX_FIELD_CHARS + 500)
    view = _item_view({"title": long_text})
    assert len(view["title"]) == _MAX_FIELD_CHARS + 1  # +1 for the ellipsis char
    assert view["title"].endswith("…")


def test_item_view_falls_back_to_whole_object_when_no_known_field():
    item = {"custom_field": "value", "another": 1}
    view = _item_view(item)
    assert view == item


def test_parse_scores_unaffected_by_prompt_encoding_choice():
    # _parse_scores only reads the classifier's JSON response — it never
    # looks at how the ITEMS block was encoded, so this must be identical
    # regardless of --legacy-json-items.
    content = json.dumps([
        {"index": 0, "score": 9, "reason": "outage"},
        {"index": 1, "score": 1, "reason": "routine"},
        {"index": 2, "score": 0, "reason": "spam"},
    ])
    scores = _parse_scores(content, len(ITEMS))
    assert scores[0]["score"] == 9
    assert scores[1]["score"] == 1
    assert scores[2]["score"] == 0
