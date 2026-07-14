"""Lightweight timeit-based benchmark for the AgentProtocol/v1 envelope
hot path (agent/protocol_v1.py).

Every tool/lifecycle/execution event that flows through the agent runtime
is built, serialized, and parsed back through ``Envelope``. This is not a
noise-sensitive regression gate (CI hardware varies) -- it is a generous
time-budget smoke test that fails loudly if the hot path regresses by an
order of magnitude (e.g. an accidental O(n^2) loop or a blocking call
introduced into construction/serialization), while reporting the measured
number so a human can track trends over time.
"""

from __future__ import annotations

import timeit

from agent.protocol_v1 import Envelope, VALID_EVENT_TYPES

ITERATIONS = 2000
# Generous budget: on typical dev/CI hardware this round-trip takes low
# single-digit microseconds. 2 ms/op leaves ~1000x headroom before this
# would fail, so it only trips on real regressions, not machine noise.
BUDGET_SECONDS_PER_OP = 0.002

_EVENT_TYPE = sorted(VALID_EVENT_TYPES)[0]


def _round_trip() -> None:
    env = Envelope.create(
        event_type=_EVENT_TYPE,
        session_id="bench-session",
        turn_id="bench-turn",
        attempt_id="bench-attempt",
        seq=1,
    )
    data = env.to_dict()
    payload = env.to_json()
    Envelope.from_dict(data)
    assert payload


def test_envelope_create_serialize_parse_round_trip_budget():
    elapsed = timeit.timeit(_round_trip, number=ITERATIONS)
    per_op = elapsed / ITERATIONS

    # Reported for humans scanning CI/local output -- this is the
    # measured number this benchmark exists to produce.
    print(
        f"\n[bench] Envelope create+to_dict+to_json+from_dict: "
        f"{per_op * 1e6:.2f} us/op over {ITERATIONS} iterations "
        f"(total {elapsed:.4f}s)"
    )

    assert per_op < BUDGET_SECONDS_PER_OP, (
        f"Envelope round-trip regressed to {per_op * 1e6:.2f} us/op "
        f"(budget {BUDGET_SECONDS_PER_OP * 1e6:.0f} us/op)"
    )
