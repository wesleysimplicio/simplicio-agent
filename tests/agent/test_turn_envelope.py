"""Issue #209: a real production call site constructs and transitions a
``TaskEnvelope``.

Unlike ``tests/agent/test_task_envelope.py`` and
``test_task_envelope_bridge.py`` (which exercise ``TaskEnvelope``/
``emit_for_transition`` in isolation, synthetically), this file calls the
actual functions that ``agent.conversation_loop.run_conversation`` and
``agent.turn_finalizer.finalize_turn`` call in production
(``agent.turn_envelope.start_turn_envelope`` / ``finish_turn_envelope``), and
the second half also drives the real ``finalize_turn`` end to end to prove
the wiring at the true call site (not a reimplementation of it).
"""

from __future__ import annotations

import importlib
import logging.handlers
import sys
import types

import pytest

from agent.task_envelope import TaskState
from agent.turn_envelope import finish_turn_envelope, start_turn_envelope
from agent.turn_finalizer import finalize_turn


class _StubBudget:
    used = 1
    max_total = 90
    remaining = 89


class _StubCompressor:
    last_prompt_tokens = 0


class _StubAgent:
    """Minimal agent surface for start_turn_envelope/finalize_turn."""

    def __init__(self):
        self.max_iterations = 90
        self.iteration_budget = _StubBudget()
        self.context_compressor = _StubCompressor()
        self.model = "stub/model"
        self.provider = "stub"
        self.base_url = "http://stub"
        self.session_id = "sess-1"
        self.quiet_mode = True
        self.platform = "cli"
        self.api_mode = "chat_completions"
        self._budget_grace_call = False
        self._checkpoint_mgr = types.SimpleNamespace(new_turn=lambda: None)
        self.valid_tool_names = set()
        self._interrupt_requested = False
        self._interrupt_message = None
        self._tool_guardrail_halt_decision = None
        self._response_was_previewed = False
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        for attr in (
            "session_input_tokens",
            "session_output_tokens",
            "session_cache_read_tokens",
            "session_cache_write_tokens",
            "session_reasoning_tokens",
            "session_prompt_tokens",
            "session_completion_tokens",
            "session_total_tokens",
            "session_estimated_cost_usd",
        ):
            setattr(self, attr, 0)
        self.session_cost_status = "ok"
        self.session_cost_source = "stub"
        self.persisted_messages = None

    def _save_trajectory(self, *a, **k):
        pass

    def _cleanup_task_resources(self, *a, **k):
        pass

    def _drop_trailing_empty_response_scaffolding(self, messages):
        pass

    def _persist_session(self, messages, conversation_history):
        self.persisted_messages = [dict(m) for m in messages]

    def _emit_status(self, *a, **k):
        pass

    def _safe_print(self, *a, **k):
        pass

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **k):
        pass


def _finalize(agent, messages, *, turn_id, interrupted, failed, final_response):
    return finalize_turn(
        agent,
        final_response=final_response,
        api_call_count=1,
        interrupted=interrupted,
        failed=failed,
        messages=messages,
        conversation_history=None,
        effective_task_id="task-1",
        turn_id=turn_id,
        user_message="do the thing",
        original_user_message="do the thing",
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )


def test_start_turn_envelope_constructs_and_reaches_executing():
    agent = _StubAgent()
    envelope = start_turn_envelope(agent, turn_id="turn-1", user_message="hi")

    assert envelope is not None
    assert envelope.state == TaskState.EXECUTING
    assert envelope.task_id == "turn-1"
    # Stashed for finish_turn_envelope to pick back up.
    assert agent._task_envelope is envelope
    # Emitter lazily created and reused.
    assert agent._protocol_emitter is not None


def test_real_run_conversation_path_starts_and_finishes_envelope(monkeypatch):
    """Exercise the actual conversation_loop call site, not a reimplementation.

    The interrupt is deliberate: it avoids a provider call while still taking
    the production prologue, envelope start, loop exit, and real finalizer.
    """
    # This checkout does not install the optional Windows rotating logger
    # dependency. Keep the test runnable by supplying its stdlib equivalent
    # before importing conversation_loop (CI has the real package installed).
    logger_module = types.ModuleType("concurrent_log_handler")
    logger_module.ConcurrentRotatingFileHandler = logging.handlers.RotatingFileHandler
    monkeypatch.setitem(sys.modules, "concurrent_log_handler", logger_module)
    loop = importlib.import_module("agent.conversation_loop")

    agent = _StubAgent()
    agent._interrupt_requested = True
    context = types.SimpleNamespace(
        user_message="hi",
        original_user_message="hi",
        messages=[{"role": "user", "content": "hi"}],
        conversation_history=None,
        active_system_prompt=None,
        effective_task_id="task-real",
        turn_id="turn-real",
        current_turn_user_idx=0,
        should_review_memory=False,
        plugin_user_context=None,
        ext_prefetch_cache=None,
    )
    monkeypatch.setattr(loop, "build_turn_context", lambda *a, **k: context)

    result = loop.run_conversation(agent, "hi")

    assert result["interrupted"] is True
    assert agent._task_envelope.task_id == "turn-real"
    assert agent._task_envelope.state is TaskState.BLOCKED
    assert agent._task_envelope_ledger.history("turn-real")[-1]["state"] == "blocked"


def test_full_turn_lifecycle_through_real_finalize_turn_reaches_closed():
    """End-to-end: start_turn_envelope (as run_conversation calls it) then
    the REAL finalize_turn (as run_conversation calls it), which internally
    calls finish_turn_envelope. Asserts the envelope that comes out the
    other end is genuinely CLOSED with an evidence receipt."""
    agent = _StubAgent()
    turn_id = "turn-closed"
    start_turn_envelope(agent, turn_id=turn_id, user_message="hi")

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]
    _finalize(
        agent,
        messages,
        turn_id=turn_id,
        interrupted=False,
        failed=False,
        final_response="hello there",
    )

    envelope = agent._task_envelope
    assert envelope.state == TaskState.CLOSED
    assert envelope.evidence_refs  # AC: closed never happens without evidence
    assert envelope.delivery_target == "chat-response"

    # The production wiring records every committed state and protocol event,
    # including the initial accepted event for envelope creation.
    assert [r["state"] for r in agent._task_envelope_ledger.history(turn_id)] == [
        "received",
        "oriented",
        "planned",
        "claimed",
        "executing",
        "validating",
        "evidence_ready",
        "delivered",
        "closed",
    ]
    assert len(agent._task_envelope_events) == 9


def test_failed_turn_drives_envelope_to_failed_via_real_finalize_turn():
    agent = _StubAgent()
    turn_id = "turn-failed"
    start_turn_envelope(agent, turn_id=turn_id, user_message="hi")

    messages = [{"role": "user", "content": "hi"}]
    _finalize(
        agent,
        messages,
        turn_id=turn_id,
        interrupted=False,
        failed=True,
        final_response=None,
    )

    assert agent._task_envelope.state == TaskState.FAILED


def test_interrupted_turn_drives_envelope_to_blocked_via_real_finalize_turn():
    agent = _StubAgent()
    turn_id = "turn-interrupted"
    start_turn_envelope(agent, turn_id=turn_id, user_message="hi")

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "partial"},
    ]
    _finalize(
        agent,
        messages,
        turn_id=turn_id,
        interrupted=True,
        failed=False,
        final_response="partial",
    )

    envelope = agent._task_envelope
    assert envelope.state == TaskState.BLOCKED
    assert envelope.block_reason


def test_finish_turn_envelope_is_noop_without_a_started_envelope():
    # Mirrors the codex_app_server bypass: no start_turn_envelope call was
    # made for this turn_id, so finalize_turn's finish call must be a
    # harmless no-op rather than raising.
    agent = _StubAgent()
    result = finish_turn_envelope(
        agent, turn_id="never-started", completed=True, failed=False, interrupted=False
    )
    assert result is None
    assert getattr(agent, "_task_envelope", None) is None


def test_mismatched_turn_id_is_a_noop():
    agent = _StubAgent()
    start_turn_envelope(agent, turn_id="turn-a", user_message="hi")
    result = finish_turn_envelope(
        agent, turn_id="turn-b", completed=True, failed=False, interrupted=False
    )
    assert result is None
    # The stale envelope for turn-a is left untouched, not force-closed.
    assert agent._task_envelope.state == TaskState.EXECUTING


def test_repeated_successful_finalize_is_idempotent():
    agent = _StubAgent()
    turn_id = "turn-idempotent"
    start_turn_envelope(agent, turn_id=turn_id, user_message="hi")
    _finalize(
        agent,
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}],
        turn_id=turn_id,
        interrupted=False,
        failed=False,
        final_response="ok",
    )
    before_history = agent._task_envelope_ledger.history(turn_id)
    before_events = tuple(agent._task_envelope_events)

    result = finish_turn_envelope(
        agent, turn_id=turn_id, completed=True, failed=False, interrupted=False
    )
    assert result is agent._task_envelope
    assert result.state is TaskState.CLOSED
    assert agent._task_envelope_ledger.history(turn_id) == before_history
    assert tuple(agent._task_envelope_events) == before_events
