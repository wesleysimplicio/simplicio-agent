"""Per-agent iteration budget — thread-safe consume/refund counter.

Extracted from ``run_agent.py``.  Each ``AIAgent`` instance (parent or
subagent) holds an :class:`IterationBudget`; the parent's cap comes from
``max_iterations`` (default 90), each subagent's cap comes from
``delegation.max_iterations`` (default 50).

``run_agent`` re-exports ``IterationBudget`` so existing
``from run_agent import IterationBudget`` imports keep working unchanged.
"""

from __future__ import annotations

import os
import threading


def resolve_max_iterations(max_iterations: int) -> int:
    """Apply env-driven overrides to the api-call ceiling.

    The blind ``max_iterations`` cap (default 90) was the end-to-end
    bottleneck observed in gateway.log: turns that needed more than 90 API
    calls stopped dead even when the iteration budget still had room. This
    lets an operator lift the ceiling without code changes:

      * ``HERMES_MAX_ITERATIONS`` (int) — absolute override of the ceiling.
      * ``HERMES_MAX_ITERATIONS_HEADROOM`` (float > 1.0) — stretch the
        ceiling by this factor when set, e.g. 2.0 doubles it. Default off
        (1.0) so unconfigured behaviour is unchanged.

    Malformed env values are ignored (the caller's value wins).
    """
    env_max = os.environ.get("HERMES_MAX_ITERATIONS")
    if env_max is not None:
        try:
            max_iterations = int(env_max)
        except ValueError:
            pass  # keep caller value on bad input
    env_headroom = os.environ.get("HERMES_MAX_ITERATIONS_HEADROOM")
    if env_headroom is not None:
        try:
            hr = float(env_headroom)
            if hr > 1.0:
                max_iterations = int(max_iterations * hr)
        except ValueError:
            pass  # keep value on bad input
    return max_iterations


class IterationBudget:
    """Thread-safe iteration counter for an agent.

    Each agent (parent or subagent) gets its own ``IterationBudget``.
    The parent's budget is capped at ``max_iterations`` (default 90).
    Each subagent gets an independent budget capped at
    ``delegation.max_iterations`` (default 50) — this means total
    iterations across parent + subagents can exceed the parent's cap.
    Users control the per-subagent limit via ``delegation.max_iterations``
    in config.yaml.

    ``execute_code`` (programmatic tool calling) iterations are refunded via
    :meth:`refund` so they don't eat into the budget.
    """

    def __init__(self, max_total: int):
        self.max_total = max_total
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Try to consume one iteration.  Returns True if allowed."""
        with self._lock:
            if self._used >= self.max_total:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """Give back one iteration (e.g. for execute_code turns)."""
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_total - self._used)


__all__ = ["IterationBudget"]
