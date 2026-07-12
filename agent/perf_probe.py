"""Per-turn latency probe (issue #244 follow-up to perf diagnosis).

The diagnosis (gateway.log) showed turns taking 677s with 69 api_calls and
1155s with 1 api_call but stuck in Discord reconnect. Serialization is
0.05ms/turn, so the bottleneck is the loop/LLM/tools/reconnect — not the fast
stack. This module gives every turn a structured latency breakdown so the
real cost center is visible instead of guessed.

It is instrumentation only: it never changes control flow, never short-circuits
the agent, and degrades to no-ops on any error. All timings are best-effort.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TurnLatencySample:
    api_calls: int = 0
    llm_seconds: float = 0.0
    tool_seconds: float = 0.0
    reconnect_seconds: float = 0.0
    other_seconds: float = 0.0
    total_seconds: float = 0.0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "api_calls": self.api_calls,
            "llm_s": round(self.llm_seconds, 2),
            "tool_s": round(self.tool_seconds, 2),
            "reconnect_s": round(self.reconnect_seconds, 2),
            "other_s": round(self.other_seconds, 2),
            "total_s": round(self.total_seconds, 2),
            "notes": self.notes,
        }


class TurnLatencyProbe:
    """Accumulates phase timings for one turn and emits a structured record.

    Phases: ``llm`` (model round-trips), ``tool`` (tool execution),
    ``reconnect`` (platform reconnect waits), ``other`` (everything else).
    """

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._phase_start: Optional[float] = None
        self._phase: Optional[str] = None
        self._sample = TurnLatencySample()

    # -- phase management -------------------------------------------------
    def begin(self, phase: str) -> None:
        """Mark the start of a phase. Auto-ends any open phase first."""
        self.end_phase()
        self._phase = phase
        self._phase_start = time.monotonic()

    def end_phase(self) -> None:
        if self._phase is None or self._phase_start is None:
            return
        dur = time.monotonic() - self._phase_start
        if self._phase == "llm":
            self._sample.llm_seconds += dur
        elif self._phase == "tool":
            self._sample.tool_seconds += dur
        elif self._phase == "reconnect":
            self._sample.reconnect_seconds += dur
        else:
            self._sample.other_seconds += dur
        self._phase = None
        self._phase_start = None

    # -- event markers ----------------------------------------------------
    def mark_api_call(self) -> None:
        self._sample.api_calls += 1

    def note(self, msg: str) -> None:
        self._sample.notes.append(msg)

    # -- finalize ---------------------------------------------------------
    def finish(self) -> TurnLatencySample:
        self.end_phase()
        self._sample.total_seconds = time.monotonic() - self._start
        return self._sample
