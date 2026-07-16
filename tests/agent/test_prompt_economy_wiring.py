"""Wiring + CI budget-gate tests for issue #196 (prompt economy in production).

``agent/prompt_economy.py`` (PR #247) shipped the compact-instruction-index
and task-pinned-capability-bundle primitives as a standalone module with no
consumer. This test file covers the actual consumer wired in
``agent/system_prompt.py``:

  * the ``agent._prompt_economy_enabled`` flag (default True, set from
    ``config.yaml`` ``agent.prompt_economy`` in ``agent/agent_init.py``)
    gates whether the compactable guidance sections
    (``prompt_economy.COMPACTABLE_HANDLES``) are folded into one compact
    block instead of shipping their full text;
  * turning the flag on must strictly shrink the stable tier and must never
    grow it;
  * every compacted handle must still be *named* in the resulting prompt (no
    invisible capability — I4 in ``agent/prompt_economy.py``);
  * the always-full sections (identity, no-fabrication / tool-use-enforcement
    / parallel-tool guidance) must be byte-identical whether the flag is on
    or off — compaction never touches safety-adjacent content;
  * a regression budget: the compact-block rendering for a fixed reference
    tool set must not silently balloon past a committed baseline (the CI
    budget gate requested by issue #196's "CI fails when fixed-core or
    representative bundle budgets regress beyond reviewed thresholds").
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.prompt_economy import COMPACTABLE_HANDLES, render_compact_block
from agent.system_prompt import build_system_prompt, build_system_prompt_parts


def _make_agent(**overrides):
    base = dict(
        load_soul_identity=False,
        skip_context_files=False,
        valid_tool_names=["memory", "session_search"],
        _task_completion_guidance=False,
        _parallel_tool_call_guidance=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=None,
        _memory_manager=None,
        _prompt_economy_enabled=False,
        model="",
        provider="",
        platform="",
        pass_session_id=False,
        session_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _stable_prompt(agent):
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_nous_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=""),
    ):
        return build_system_prompt_parts(agent)["stable"]


def _full_prompt(agent):
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_nous_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=""),
    ):
        return build_system_prompt(agent)


class TestPromptEconomyModes:
    def test_flag_missing_entirely_uses_compact_default(self, monkeypatch):
        """A code path that bypasses agent_init (no ``_prompt_economy_enabled``
        attribute at all) must match the missing-config compact default."""
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        agent = _make_agent()
        del agent._prompt_economy_enabled
        stable = _stable_prompt(agent)
        from agent.prompt_builder import MEMORY_GUIDANCE

        assert "Compact capability index" in stable
        assert "sec:memory" in stable
        assert MEMORY_GUIDANCE.strip() not in stable

    def test_off_ships_full_guidance_text(self, monkeypatch):
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        agent = _make_agent(_prompt_economy_enabled=False)
        stable = _stable_prompt(agent)
        assert "Compact capability index" not in stable
        # Full MEMORY_GUIDANCE text is present verbatim.
        from agent.prompt_builder import MEMORY_GUIDANCE

        assert MEMORY_GUIDANCE.strip() in stable


def test_production_prompt_build_records_size_receipt_without_changing_prompt():
    agent = _make_agent(
        _prompt_economy_enabled=True,
        tools=[{"name": "memory", "description": "Read memory."}],
    )

    first = _full_prompt(agent)
    first_receipt = agent._last_prompt_economy_measurement
    second = _full_prompt(agent)
    second_receipt = agent._last_prompt_economy_measurement

    assert first == second
    assert first_receipt.prompt_chars == len(first)
    assert first_receipt.prompt_bytes == len(first.encode("utf-8"))
    assert first_receipt.tool_count == 1
    assert first_receipt == second_receipt
    assert first_receipt.prompt_sha256 == second_receipt.prompt_sha256


class TestPromptEconomyConfigDefault:
    def test_missing_config_enables_compaction(self):
        from agent.agent_init import _prompt_economy_enabled

        assert _prompt_economy_enabled({}) is True

    def test_explicit_false_preserves_full_guidance_opt_out(self):
        from agent.agent_init import _prompt_economy_enabled

        assert _prompt_economy_enabled({"prompt_economy": False}) is False


class TestPromptEconomyOnShrinksStableTier:
    def test_strictly_smaller_when_enabled(self, monkeypatch):
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        off = _stable_prompt(_make_agent(_prompt_economy_enabled=False))
        on = _stable_prompt(_make_agent(_prompt_economy_enabled=True))
        assert len(on) < len(off), "enabling prompt economy must shrink the stable tier"

    def test_never_grows(self, monkeypatch):
        """Regression guard: whatever else changes upstream, flipping the
        flag on must never produce a LARGER stable tier than off."""
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        for tools in (["memory"], ["session_search"], ["memory", "session_search"], []):
            off = _stable_prompt(_make_agent(valid_tool_names=tools, _prompt_economy_enabled=False))
            on = _stable_prompt(_make_agent(valid_tool_names=tools, _prompt_economy_enabled=True))
            assert len(on) <= len(off)

    def test_compact_block_names_every_active_handle(self, monkeypatch):
        """No invisible capability: each compacted section's handle string
        must still be present in the assembled prompt."""
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        agent = _make_agent(valid_tool_names=["memory", "session_search"], _prompt_economy_enabled=True)
        stable = _stable_prompt(agent)
        assert "sec:hermes-help" in stable
        assert "sec:memory" in stable
        assert "sec:session-search" in stable

    def test_full_text_absent_for_compacted_handles(self, monkeypatch):
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        agent = _make_agent(valid_tool_names=["memory", "session_search"], _prompt_economy_enabled=True)
        stable = _stable_prompt(agent)
        from agent.prompt_builder import HERMES_AGENT_HELP_GUIDANCE, MEMORY_GUIDANCE, SESSION_SEARCH_GUIDANCE

        assert HERMES_AGENT_HELP_GUIDANCE.strip() not in stable
        assert MEMORY_GUIDANCE.strip() not in stable
        assert SESSION_SEARCH_GUIDANCE.strip() not in stable


class TestAlwaysFullSectionsUnaffected:
    """Safety-adjacent sections must be byte-identical regardless of the
    prompt-economy flag — compaction must never touch them."""

    def test_task_completion_and_tool_use_enforcement_untouched(self, monkeypatch):
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        common = dict(
            valid_tool_names=["memory"],
            _task_completion_guidance=True,
            _tool_use_enforcement=True,
            model="gpt-5",
        )
        off = _stable_prompt(_make_agent(_prompt_economy_enabled=False, **common))
        on = _stable_prompt(_make_agent(_prompt_economy_enabled=True, **common))

        from agent.prompt_builder import (
            OPENAI_MODEL_EXECUTION_GUIDANCE,
            TASK_COMPLETION_GUIDANCE,
            TOOL_USE_ENFORCEMENT_GUIDANCE,
        )

        for block in (TASK_COMPLETION_GUIDANCE, TOOL_USE_ENFORCEMENT_GUIDANCE, OPENAI_MODEL_EXECUTION_GUIDANCE):
            assert block.strip() in off
            assert block.strip() in on


class TestCompactableHandlesAreConservative:
    """Guard against silently widening COMPACTABLE_HANDLES to cover a
    safety-adjacent category without an explicit, reviewed decision."""

    def test_identity_and_behavior_categories_never_compactable(self):
        from agent.prompt_economy import INSTRUCTION_CATALOG

        by_handle = {e["handle"]: e for e in INSTRUCTION_CATALOG}
        for handle in COMPACTABLE_HANDLES:
            assert by_handle[handle]["category"] not in {"identity", "behavior"}


# ───────────────────────────────────────────────────────────────────────
# CI budget gate — regression guard on the compact-block rendering itself
# ───────────────────────────────────────────────────────────────────────

# Baseline captured from the current render_compact_block() output for the
# full COMPACTABLE_HANDLES set (issue #196). Update deliberately (with
# review) if a catalog summary genuinely needs to grow; a silent regression
# here is exactly the "fixed-core budget regressed" failure issue #196 asks
# CI to catch.
_COMPACT_BLOCK_CHAR_BUDGET = 800


def test_compact_block_stays_within_ci_budget():
    block = render_compact_block(sorted(COMPACTABLE_HANDLES))
    assert block, "compact block must render for the full compactable set"
    assert len(block) <= _COMPACT_BLOCK_CHAR_BUDGET, (
        f"compact instruction block grew to {len(block)} chars, "
        f"budget is {_COMPACT_BLOCK_CHAR_BUDGET} — issue #196 CI budget gate"
    )


def test_compact_block_always_smaller_than_full_text_it_replaces():
    """The whole point of progressive disclosure: the compact rendering must
    stay strictly smaller than shipping every compactable section in full."""
    from agent.prompt_builder import (
        HERMES_AGENT_HELP_GUIDANCE,
        KANBAN_GUIDANCE,
        MEMORY_GUIDANCE,
        SESSION_SEARCH_GUIDANCE,
        SKILLS_GUIDANCE,
    )

    full_total = sum(
        len(t)
        for t in (
            HERMES_AGENT_HELP_GUIDANCE,
            MEMORY_GUIDANCE,
            SESSION_SEARCH_GUIDANCE,
            SKILLS_GUIDANCE,
            KANBAN_GUIDANCE,
        )
    )
    compact = render_compact_block(sorted(COMPACTABLE_HANDLES))
    assert len(compact) < full_total
    # Required in the issue: at least a 3x reduction for the covered slice
    # (mirrors the ratio already asserted for the raw index in
    # tests/agent/test_prompt_economy.py::test_index_is_small_fraction_of_full_text).
    assert len(compact) * 3 <= full_total


def test_render_compact_block_empty_when_no_active_handles():
    assert render_compact_block([]) == ""
    assert render_compact_block(["sec:task-completion"]) == "", (
        "a non-compactable handle must never appear in the compact block"
    )
