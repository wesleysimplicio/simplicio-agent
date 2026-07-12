"""Tests for the Discord/relay reconnect backoff (Slice C, issue #244).

gateway.log showed a 1155.3s/1-api-call stall caused by an unbounded Discord
reconnect cascade. This module proves the reconnect delay:

  (a) never exceeds the 30s cap (no more 1155s stalls),
  (b) varies between calls (jitter — avoids thundering herd), yet stays capped,
  (c) is bounded for every attempt, including pathological high attempt counts.

The helper is pure and deterministic-friendly: inject a seeded ``random.Random``
so the jitter is reproducible.
"""

from __future__ import annotations

import random

import pytest

from gateway.relay.ws_transport import (
    RECONNECT_BACKOFF_CAP_S,
    compute_reconnect_delay,
)


def test_cap_never_exceeded():
    """No attempt — even attempt 100 — may wait longer than the 30s cap."""
    for attempt in (0, 1, 2, 5, 10, 20, 100):
        for seed in range(5):
            rng = random.Random(seed)
            delay = compute_reconnect_delay(attempt, rng=rng)
            assert 0 <= delay <= RECONNECT_BACKOFF_CAP_S, (
                f"attempt={attempt} seed={seed} produced delay={delay} "
                f"(cap={RECONNECT_BACKOFF_CAP_S})"
            )


def test_no_1155s_wait():
    """The exact failure mode from gateway.log (1155.3s) must be impossible."""
    rng = random.Random(0)
    for attempt in range(0, 50):
        assert compute_reconnect_delay(attempt, rng=rng) <= 30.0


def test_jitter_varies_but_stays_capped():
    """Multiple calls vary (not a fixed schedule) yet all stay <= cap."""
    rng = random.Random(1234)
    delays = [compute_reconnect_delay(8, rng=rng) for _ in range(20)]
    # Jitter must produce spread across the 20 samples.
    assert max(delays) - min(delays) > 1e-6
    # Every sample respects the ceiling.
    assert all(0 < d <= RECONNECT_BACKOFF_CAP_S for d in delays)


def test_base_attempt_is_small_and_positive():
    """First reconnect should be near the 1s base, jittered, never zero."""
    rng = random.Random(7)
    for _ in range(10):
        d = compute_reconnect_delay(0, rng=rng)
        assert 0.0 < d <= 1.5  # base 1.0 ± 50% jitter


def test_negative_attempt_clamped():
    """Defensive: a negative attempt must not blow up or return < 0."""
    rng = random.Random(3)
    assert compute_reconnect_delay(-1, rng=rng) >= 0.0


def test_deterministic_with_injected_rng():
    """Same seed -> same delay (so the test is reproducible, not flaky)."""
    a = compute_reconnect_delay(6, rng=random.Random(99))
    b = compute_reconnect_delay(6, rng=random.Random(99))
    assert a == b
