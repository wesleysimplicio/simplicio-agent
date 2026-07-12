"""Integration test: TurnLatencyProbe is wired into finalize_turn log output.

Verifies that an agent carrying ``_latency_probe`` produces a ``turn_latency=``
field in the "Turn ended" diagnostic line, without changing control flow.
"""

import logging

from agent.perf_probe import TurnLatencyProbe
from agent.turn_finalizer import finalize_turn


class _Budget:
    remaining = 5
    used = 3
    max_total = 10


class _FakeAgent:
    """Minimal agent stub. Any undefined attribute resolves to a no-op
    callable so finalize_turn's many side-effect calls don't crash; the
    fields we actually assert on are defined explicitly below."""

    max_iterations = 10
    iteration_budget = _Budget()
    session_id = "sess-test"
    quiet_mode = True
    model = "fake-model"
    session_cost_source = "test"
    _tool_guardrail_halt_decision = None
    _iters_since_skill = 0
    _skill_nudge_interval = 0
    valid_tool_names = []
    _latency_probe = None  # type: ignore[assignment]

    def __getattr__(self, name):
        # no-op for any method finalize_turn calls that we didn't define
        def _noop(*a, **k):
            return None
        return _noop

    def _emit_status(self, *a, **k):
        pass

    def _safe_print(self, *a, **k):
        pass


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture_logger():
    """Capture records emitted on the agent.conversation_loop logger."""
    import agent.conversation_loop as cl

    handler = _CaptureHandler()
    cl.logger.addHandler(handler)
    cl.logger.setLevel(logging.DEBUG)
    return handler.records, handler


def test_finalize_turn_emits_turn_latency():
    agent = _FakeAgent()
    agent._latency_probe = TurnLatencyProbe()
    # simulate some phases
    agent._latency_probe.begin("llm")
    agent._latency_probe.mark_api_call()
    agent._latency_probe.begin("tool")

    records, handler = _capture_logger()
    try:
        finalize_turn(
            agent,
            final_response="ok",
            api_call_count=3,
            interrupted=False,
            failed=False,
            messages=[{"role": "user", "content": "hi"}],
            conversation_history=[],
            effective_task_id="t1",
            turn_id="turn1",
            user_message="hi",
            original_user_message="hi",
            _should_review_memory=False,
            _turn_exit_reason="completed",
        )
    finally:
        import agent.conversation_loop as cl

        cl.logger.removeHandler(handler)

    turn_lines = [
        r.getMessage()
        for r in records
        if "Turn ended" in r.getMessage()
    ]
    assert turn_lines, "no 'Turn ended' line logged"
    assert "turn_latency=" in turn_lines[0], turn_lines[0]
    # the probe should have been finalized (total_s present)
    assert "total=" in turn_lines[0]


def test_finalize_turn_without_probe_is_safe():
    agent = _FakeAgent()  # no _latency_probe
    records, handler = _capture_logger()
    try:
        finalize_turn(
            agent,
            final_response="ok",
            api_call_count=1,
            interrupted=False,
            failed=False,
            messages=[],
            conversation_history=[],
            effective_task_id="t1",
            turn_id="turn1",
            user_message="hi",
            original_user_message="hi",
            _should_review_memory=False,
            _turn_exit_reason="completed",
        )
    finally:
        import agent.conversation_loop as cl

        cl.logger.removeHandler(handler)

    turn_lines = [r.getMessage() for r in records if "Turn ended" in r.getMessage()]
    assert turn_lines
    assert "turn_latency=n/a" in turn_lines[0]
