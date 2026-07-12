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
    assert set(d.keys()) >= {"api_calls", "llm_s", "tool_s", "reconnect_s", "other_s", "total_s", "notes"}
