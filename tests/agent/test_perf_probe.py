"""Tests for TurnLatencyProbe (instrumentation only, no control-flow change)."""

import time

from agent.perf_probe import TurnLatencyProbe, TurnLatencySample


def test_phase_accounting():
    p = TurnLatencyProbe()
    p.begin("llm")
    time.sleep(0.01)
    p.end_phase()
    p.begin("tool")
    time.sleep(0.01)
    p.end_phase()
    s = p.finish()
    assert isinstance(s, TurnLatencySample)
    assert s.llm_seconds > 0.005
    assert s.tool_seconds > 0.005
    assert s.api_calls == 0


def test_begin_switches_phase_implicitly():
    p = TurnLatencyProbe()
    p.begin("llm")
    time.sleep(0.005)
    p.begin("reconnect")  # should auto-end llm
    time.sleep(0.005)
    s = p.finish()
    assert s.llm_seconds > 0.003
    assert s.reconnect_seconds > 0.003


def test_api_call_and_notes():
    p = TurnLatencyProbe()
    p.mark_api_call()
    p.mark_api_call()
    p.note("reconnect backoff 30s->60s")
    s = p.finish()
    assert s.api_calls == 2
    assert "reconnect backoff" in s.notes[0]
    assert s.total_seconds >= 0.0


def test_as_dict_serializable():
    p = TurnLatencyProbe()
    p.mark_api_call()
    d = p.finish().as_dict()
    assert d["api_calls"] == 1
    assert set(d.keys()) >= {
        "api_calls", "tool_calls", "ttft_s", "llm_s", "tool_s", "reconnect_s", "other_s", "total_s", "notes",
    }


def test_mark_tool_calls_accumulates():
    p = TurnLatencyProbe()
    p.mark_tool_calls(3)
    p.mark_tool_calls(2)
    s = p.finish()
    assert s.tool_calls == 5


def test_mark_tool_calls_ignores_negative():
    p = TurnLatencyProbe()
    p.mark_tool_calls(-5)
    s = p.finish()
    assert s.tool_calls == 0


def test_mark_first_token_records_measured_ttft():
    p = TurnLatencyProbe()
    time.sleep(0.01)
    p.mark_first_token()
    s = p.finish()
    assert s.ttft_seconds is not None
    assert s.ttft_seconds >= 0.005


def test_mark_first_token_is_idempotent():
    """Only the FIRST call sets ttft_seconds — a retried/second stream
    attempt within the same turn must not overwrite the real first-token
    latency with a later, larger one."""
    p = TurnLatencyProbe()
    time.sleep(0.01)
    p.mark_first_token()
    ttft_after_first_call = p._sample.ttft_seconds
    time.sleep(0.01)
    p.mark_first_token()  # should be a no-op
    assert p._sample.ttft_seconds == ttft_after_first_call


def test_ttft_seconds_is_none_when_never_streamed():
    """A turn that never streams (non-streaming provider path) must report
    ttft_s as None, not a fabricated 0 — a real absence of measurement."""
    p = TurnLatencyProbe()
    s = p.finish()
    assert s.ttft_seconds is None
    assert s.as_dict()["ttft_s"] is None
