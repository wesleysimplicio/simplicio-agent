"""Tests for agent/prompt_economy.py — issue #196 prompt economy.

Proves the three required invariants:

  (a) ``resolve_instruction_index`` returns short handles, NOT the full
      ~72k-char instruction body.
  (b) ``pin_capability_bundle`` is order-stable: identical
      ``(tools, task)`` input yields identical ordering every call.
  (c) ``pin_capability_bundle`` preserves total tool availability: every
      input tool (here the canonical 29 tools) is still listed in the bundle,
      only the *order* is pinned.

The module is intentionally dependency-light; tests prefer the public API and
only fall back to the live registry when importable.
"""

from __future__ import annotations

import pytest

from agent.prompt_economy import (
    ExpansionReceipt,
    INSTRUCTION_CATALOG,
    expand_instruction_with_receipt,
    instruction_index_full_size,
    instruction_index_summary_size,
    instruction_expansion_receipt,
    pin_capability_bundle,
    pin_capability_bundle_names,
    resolve_instruction_index,
)


# Canonical tool set called out in the issue (29 tools). Every one of these
# must survive pinning untouched — only the order may change.
CANONICAL_29 = [
    "web_search",
    "web_extract",
    "terminal",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "vision_analyze",
    "image_generate",
    "video_generate",
    "text_to_speech",
    "browser_navigate",
    "browser_snapshot",
    "computer_use",
    "memory",
    "session_search",
    "skills_list",
    "skill_view",
    "skill_manage",
    "todo",
    "process",
    "cronjob",
    "spotify_search",
    "spotify_playback",
    "x_search",
    "kanban_show",
    "send_message",
    "delegate",
    "home_assistant",
]


# Some of those names carry a description so the relevance ranking has signal.
_DESCRIPTIONS = {
    "web_search": "Search the web for information.",
    "web_extract": "Extract article text from a URL.",
    "terminal": "Run a shell command on the host.",
    "read_file": "Read a text file with line numbers.",
    "write_file": "Write content to a file.",
    "patch": "Targeted find-and-replace edits in files.",
    "search_files": "Search file contents or find files by name.",
    "vision_analyze": "Analyze an image with vision.",
    "image_generate": "Generate an image from a text prompt.",
    "video_generate": "Generate a video from a text prompt.",
    "text_to_speech": "Convert text to speech audio.",
    "browser_navigate": "Navigate to a URL in the browser.",
    "browser_snapshot": "Snapshot the current page accessibility tree.",
    "computer_use": "Drive the host desktop (click, type, screenshot).",
    "memory": "Read or write durable agent memory.",
    "session_search": "Search past sessions for context.",
    "skills_list": "List available skills.",
    "skill_view": "View a skill's full content.",
    "skill_manage": "Create, patch, or edit skills.",
    "todo": "Manage the task todo list.",
    "process": "Manage background processes.",
    "cronjob": "Schedule recurring jobs.",
    "spotify_search": "Search Spotify for tracks.",
    "spotify_playback": "Control Spotify playback.",
    "x_search": "Search posts on X / Twitter.",
    "kanban_show": "Show the kanban board for this task.",
    "send_message": "Send a message to a user or channel.",
    "delegate": "Delegate a task to a subagent.",
    "home_assistant": "Control Home Assistant devices.",
}


def _canonical_tools():
    """Return the 29 canonical tools as {name, description} dicts."""
    return [{"name": n, "description": _DESCRIPTIONS.get(n, "")} for n in CANONICAL_29]


# ───────────────────────────────────────────────────────────────────────
# (a) Index returns short handles, not the full instruction body
# ───────────────────────────────────────────────────────────────────────


class TestInstructionIndexReturnsHandlesNotFullText:
    def test_index_shape(self):
        idx = resolve_instruction_index()
        assert idx, "index must not be empty"
        for entry in idx:
            assert set(entry) == {"handle", "title", "summary", "category"}
            # Handles are short identifiers, never prose.
            assert len(entry["handle"]) < 40
            assert entry["handle"].startswith("sec:")
            # Summaries are one-liners, not the full section text.
            assert len(entry["summary"]) < 200

    def test_index_is_small_fraction_of_full_text(self):
        # The whole point: the compact index is a tiny fraction of shipping
        # the entire instruction body. The compact index (handles + one-line
        # summaries) must be at least 3x smaller than the full-body payload,
        # and strictly smaller whenever full bodies are resolvable.
        summary_size = instruction_index_summary_size()
        full_size = instruction_index_full_size()
        if full_size > 0:
            assert summary_size < full_size
            assert summary_size * 3 <= full_size

    def test_no_full_body_leaks_into_index(self):
        idx = resolve_instruction_index()
        # Concatenate whatever the index ships.
        payload = " ".join(
            f"{e['handle']} {e['title']} {e['summary']} {e['category']}" for e in idx
        )
        # Real full section bodies are multi-hundred-char blocks; none should
        # be present verbatim in the compact payload.
        for entry in INSTRUCTION_CATALOG:
            full = None
            if not entry["symbol"].startswith("_"):
                try:
                    import agent.prompt_builder as pb

                    v = getattr(pb, entry["symbol"], None)
                    if isinstance(v, str):
                        full = v
                except Exception:
                    full = None
            if full and len(full) > 200:
                # The compact index must NOT contain the verbatim full text.
                assert full.strip() not in payload, (
                    f"full body for {entry['handle']} leaked into compact index"
                )

    def test_index_order_is_stable(self):
        a = resolve_instruction_index()
        b = resolve_instruction_index()
        assert [e["handle"] for e in a] == [e["handle"] for e in b]


# ───────────────────────────────────────────────────────────────────────
# (b) Bundle pinning is order-stable (same input -> same order)
# ───────────────────────────────────────────────────────────────────────


class TestBundlePinningIsStable:
    def test_same_input_same_order(self):
        tools = _canonical_tools()
        task = "search the web and read a file"
        first = pin_capability_bundle(tools, task=task)
        # Call again — must be identical ordering.
        for _ in range(5):
            again = pin_capability_bundle(tools, task=task)
            assert [t["name"] for t in again] == [t["name"] for t in first]

    def test_string_and_dict_inputs_both_preserve_set(self):
        # Names-only input carries no description signal, so its pinned order
        # can differ from dicts-with-descriptions (that's intended — richer
        # metadata ranks better). The key invariant is that BOTH preserve the
        # complete tool set; neither drops a tool.
        names = list(CANONICAL_29)
        task = "run a shell command and patch a file"
        from_names = pin_capability_bundle_names(names, task=task)
        from_dicts = pin_capability_bundle_names(_canonical_tools(), task=task)
        # Each individually preserves the full 29-tool set.
        assert sorted(from_names) == sorted(CANONICAL_29)
        assert sorted(from_dicts) == sorted(CANONICAL_29)
        # Both are deterministic for their own input shape.
        assert from_names == pin_capability_bundle_names(names, task=task)
        assert from_dicts == pin_capability_bundle_names(_canonical_tools(), task=task)

    def test_same_order_across_process_like_calls(self):
        # Re-import-free determinism: build the bundle twice from scratch.
        tools_a = [
            {"name": n, "description": _DESCRIPTIONS.get(n, "")} for n in CANONICAL_29
        ]
        tools_b = [
            {"name": n, "description": _DESCRIPTIONS.get(n, "")} for n in CANONICAL_29
        ]
        assert pin_capability_bundle_names(tools_a, "deploy the agent") == (
            pin_capability_bundle_names(tools_b, "deploy the agent")
        )

    def test_no_randomness(self):
        import random

        tools = _canonical_tools()
        before = random.getstate()
        try:
            a = pin_capability_bundle_names(tools, "build a feature")
        finally:
            random.setstate(before)
        b = pin_capability_bundle_names(tools, "build a feature")
        assert a == b


# ───────────────────────────────────────────────────────────────────────
# (c) Total tool availability preserved (all 29 tools listed, order only)
# ───────────────────────────────────────────────────────────────────────


class TestToolAvailabilityPreserved:
    def test_all_29_tools_present(self):
        tools = _canonical_tools()
        assert len(tools) == 29, "fixture must list the canonical 29 tools"
        bundle = pin_capability_bundle(tools, task="search the web and read a file")
        # Same count — nothing dropped, nothing added.
        assert len(bundle) == 29
        bundled_names = [t["name"] for t in bundle]
        # Exact set preserved (multiset equality).
        assert sorted(bundled_names) == sorted(CANONICAL_29)
        # Every individual canonical tool is present.
        for name in CANONICAL_29:
            assert name in bundled_names

    def test_no_tool_removed_even_for_unrelated_task(self):
        tools = _canonical_tools()
        # An utterly unrelated task must still keep every tool.
        bundle = pin_capability_bundle(tools, task="frobnicate the quark lattice")
        assert sorted(t["name"] for t in bundle) == sorted(CANONICAL_29)

    def test_schemas_preserved(self):
        tools = _canonical_tools()
        bundle = pin_capability_bundle(tools, task="read and write files")
        # Names + descriptions are byte-identical to the input (only order
        # may differ), so cached tool schemas stay valid.
        by_name_in = {t["name"]: t for t in tools}
        by_name_out = {t["name"]: t for t in bundle}
        assert set(by_name_in) == set(by_name_out)
        for name in by_name_in:
            assert by_name_in[name]["description"] == by_name_out[name]["description"]

    def test_order_is_pinned_not_random(self):
        # The pinned order for a task is deterministic — call with a fresh
        # list and confirm identical head (relevant tools float up).
        tools = _canonical_tools()
        order = pin_capability_bundle_names(tools, "search the web")
        assert order[0] == "web_search"  # literally named for the task

    def test_live_registry_roundtrip(self):
        """Against the real tool registry, if importable: full availability."""
        try:
            from tools.registry import registry
        except Exception:
            pytest.skip("tools.registry not importable in this environment")
        names = registry.get_all_tool_names()
        if not names:
            pytest.skip("registry has no tools registered in this environment")
        bundle = pin_capability_bundle_names(names, task="read and patch files")
        # Total availability preserved against the live set.
        assert sorted(bundle) == sorted(names)
        # Cache-stable: identical second call.
        assert pin_capability_bundle_names(names, task="read and patch files") == bundle


def test_index_plus_bundle_compose():
    """Smoke: the two pieces of the prompt-economy layer compose cleanly."""
    idx = resolve_instruction_index()
    bundle = pin_capability_bundle(_canonical_tools(), task="send a message")
    assert idx and bundle
    assert len(bundle) == 29


# ───────────────────────────────────────────────────────────────────────
# (d) Expansion receipts are deterministic and fallback-safe
# ───────────────────────────────────────────────────────────────────────


class TestExpansionReceipts:
    def test_receipt_is_deterministic_and_json_friendly(self):
        tools = _canonical_tools()
        first_text, first = expand_instruction_with_receipt(
            "sec:memory", tools=tools, task="read and write memory"
        )
        second_text, second = expand_instruction_with_receipt(
            "sec:memory", tools=tools, task="read and write memory"
        )

        assert isinstance(first, ExpansionReceipt)
        assert first_text == second_text
        assert first == second
        assert first.sha256 == first.content_sha256 == first.content_hash
        assert first.size == first.bytes == len(first_text.encode("utf-8"))
        assert first.chars == len(first_text)
        assert first.selected_bundle == tuple(
            pin_capability_bundle_names(tools, task="read and write memory")
        )
        assert first.to_dict() == first.as_dict()
        assert first.to_dict()["selected_bundle"] == list(first.selected_bundle)

    def test_default_expansion_is_append_only_cache_safe(self):
        _text, receipt = expand_instruction_with_receipt("sec:session-search")
        assert receipt.cache_stable is True
        assert receipt.prefix_invalidated is False
        assert receipt.fallback is False
        assert receipt.fallback_reason == ""

    def test_explicit_fallback_handles_unknown_handle(self):
        text, receipt = expand_instruction_with_receipt(
            "sec:future", fallback="Use the future capability safely."
        )
        assert text == "Use the future capability safely."
        assert receipt.fallback is True
        assert receipt.fallback_reason == "unknown_handle"
        assert receipt.handle == "sec:future"

    def test_known_handle_falls_back_when_body_is_unavailable(self, monkeypatch):
        import agent.prompt_economy as economy

        monkeypatch.setattr(economy, "_catalog_symbol_value", lambda _symbol: None)
        text, receipt = expand_instruction_with_receipt(
            "sec:memory", fallback="Caller-provided memory fallback."
        )
        assert text == "Caller-provided memory fallback."
        assert receipt.fallback is True
        assert receipt.fallback_reason == "body_unavailable"

    def test_catalog_summary_is_the_final_known_handle_fallback(self, monkeypatch):
        import agent.prompt_economy as economy

        monkeypatch.setattr(economy, "_catalog_symbol_value", lambda _symbol: None)
        text, receipt = expand_instruction_with_receipt("sec:memory")
        assert text == next(
            e["summary"] for e in INSTRUCTION_CATALOG if e["handle"] == "sec:memory"
        )
        assert receipt.fallback is True
        assert receipt.fallback_reason == "body_unavailable:catalog_summary"

    def test_prefix_invalidation_is_never_reported_as_cache_stable(self):
        _text, receipt = expand_instruction_with_receipt(
            "sec:memory", cache_stable=True, prefix_invalidated=True
        )
        assert receipt.prefix_invalidated is True
        assert receipt.cache_stable is False

    def test_receipt_only_helper_matches_expansion(self):
        text, receipt = expand_instruction_with_receipt("sec:skills")
        assert instruction_expansion_receipt("sec:skills") == receipt
        assert receipt.chars == len(text)
