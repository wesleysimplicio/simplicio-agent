"""Unit tests for agent/tier_rate_limiter.py (issue #70).

Covers token-bucket refill math, try_acquire boundary conditions, the
rate_override opt-in parameter, and the rate_limited decorator.
"""

from __future__ import annotations

import time

import pytest

from agent.tier_rate_limiter import (
    RateLimitExceeded,
    TierRateLimiter,
    _TokenBucket,
    rate_limited,
)


class TestTokenBucket:
    def test_starts_full(self):
        bucket = _TokenBucket(rate_per_minute=60.0)
        assert bucket.tokens == 60.0

    def test_try_consume_deducts_tokens(self):
        bucket = _TokenBucket(rate_per_minute=60.0)
        assert bucket.try_consume(1.0) is True
        assert bucket.tokens == pytest.approx(59.0, abs=0.01)

    def test_try_consume_fails_when_depleted(self):
        bucket = _TokenBucket(rate_per_minute=1.0)
        assert bucket.try_consume(1.0) is True
        assert bucket.try_consume(1.0) is False

    def test_refill_adds_tokens_over_time(self):
        bucket = _TokenBucket(rate_per_minute=60.0)  # 1 token/sec
        bucket.tokens = 0.0
        bucket.last_refill = time.monotonic() - 2.0  # simulate 2s elapsed
        bucket.refill()
        assert bucket.tokens == pytest.approx(2.0, abs=0.1)

    def test_refill_never_exceeds_capacity(self):
        bucket = _TokenBucket(rate_per_minute=60.0)
        bucket.tokens = 60.0
        bucket.last_refill = time.monotonic() - 100.0  # huge elapsed time
        bucket.refill()
        assert bucket.tokens == 60.0  # capped, not 100+

    def test_boundary_exact_token_count_succeeds(self):
        bucket = _TokenBucket(rate_per_minute=60.0)
        bucket.tokens = 5.0
        assert bucket.try_consume(5.0) is True
        # approx: refill() runs a hair of wall-clock time after `tokens` was
        # set above, adding a negligible fraction back before consuming.
        assert bucket.tokens == pytest.approx(0.0, abs=0.01)

    def test_boundary_one_token_short_fails(self):
        bucket = _TokenBucket(rate_per_minute=60.0)
        bucket.tokens = 4.999
        assert bucket.try_consume(5.0) is False
        assert bucket.tokens == pytest.approx(4.999, abs=0.001)  # unchanged on failure


class TestTierRateLimiter:
    def test_lazy_bucket_creation_uses_default_rate(self, monkeypatch):
        monkeypatch.delenv("HERMES_TIER_RATE_LIMIT_RESEARCH", raising=False)
        limiter = TierRateLimiter()
        assert limiter.remaining("research") == 60.0  # default before any bucket exists

    def test_env_var_configures_tier_rate(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_RESEARCH", "10")
        limiter = TierRateLimiter()
        limiter.try_acquire("research")  # creates the bucket, reading the env
        assert limiter.remaining("research") == pytest.approx(9.0, abs=0.1)

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_RESEARCH", "not-a-number")
        limiter = TierRateLimiter()
        limiter.try_acquire("research")
        assert limiter.remaining("research") == pytest.approx(59.0, abs=0.1)  # default 60/min

    def test_non_positive_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_RESEARCH", "0")
        limiter = TierRateLimiter()
        limiter.try_acquire("research")
        assert limiter.remaining("research") == pytest.approx(59.0, abs=0.1)

    def test_try_acquire_boundary_exact_depletion(self):
        limiter = TierRateLimiter()
        limiter._buckets["t"] = _TokenBucket(rate_per_minute=3.0)
        assert limiter.try_acquire("t") is True
        assert limiter.try_acquire("t") is True
        assert limiter.try_acquire("t") is True
        assert limiter.try_acquire("t") is False  # bucket exactly depleted

    def test_try_acquire_zero_tokens_always_succeeds(self):
        limiter = TierRateLimiter()
        limiter._buckets["t"] = _TokenBucket(rate_per_minute=0.001)
        limiter.try_acquire("t", tokens=1)  # deplete it
        assert limiter.try_acquire("t", tokens=0) is True

    def test_different_tiers_have_independent_buckets(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_A", "1")
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_B", "1")
        limiter = TierRateLimiter()
        assert limiter.try_acquire("a") is True
        assert limiter.try_acquire("a") is False  # a's bucket depleted
        assert limiter.try_acquire("b") is True  # b unaffected

    def test_reset_tier_restores_full_capacity(self):
        limiter = TierRateLimiter()
        limiter._buckets["t"] = _TokenBucket(rate_per_minute=1.0)
        limiter.try_acquire("t")
        assert limiter.try_acquire("t") is False
        limiter.reset_tier("t")
        assert limiter.try_acquire("t") is True

    def test_reset_all_clears_every_tier(self):
        limiter = TierRateLimiter()
        limiter._buckets["a"] = _TokenBucket(rate_per_minute=1.0)
        limiter._buckets["b"] = _TokenBucket(rate_per_minute=1.0)
        limiter.try_acquire("a")
        limiter.try_acquire("b")
        limiter.reset_all()
        assert limiter.try_acquire("a") is True
        assert limiter.try_acquire("b") is True

    def test_thread_safety_no_double_spend_under_contention(self):
        """N threads racing to acquire from a bucket with exactly N tokens
        must all succeed exactly once each — no double-spend, no starvation
        from a race in refill+consume."""
        import threading

        limiter = TierRateLimiter()
        N = 20
        limiter._buckets["t"] = _TokenBucket(rate_per_minute=float(N))
        results = []
        results_lock = threading.Lock()

        def racer():
            ok = limiter.try_acquire("t")
            with results_lock:
                results.append(ok)

        threads = [threading.Thread(target=racer) for _ in range(N * 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert sum(results) == N  # exactly N succeeded, not more


class TestRateOverride:
    def test_rate_override_seeds_new_bucket(self):
        limiter = TierRateLimiter()
        limiter.try_acquire("t", rate_override=5.0)
        assert limiter.remaining("t") == pytest.approx(4.0, abs=0.1)  # 5 - 1

    def test_rate_override_ignored_on_existing_bucket(self):
        """An already-created bucket keeps its original rate — passing a
        different override later is a caller bug, not silently honored."""
        limiter = TierRateLimiter()
        limiter.try_acquire("t", rate_override=100.0)
        assert limiter.remaining("t") == pytest.approx(99.0, abs=0.1)
        limiter.try_acquire("t", rate_override=5.0)  # should NOT reset capacity to 5
        assert limiter.remaining("t") == pytest.approx(98.0, abs=0.1)  # still on the 100-rate bucket

    def test_none_override_preserves_env_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_T", "42")
        limiter = TierRateLimiter()
        limiter.try_acquire("t", rate_override=None)
        assert limiter.remaining("t") == pytest.approx(41.0, abs=0.1)

    def test_non_positive_override_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("HERMES_TIER_RATE_LIMIT_T", "42")
        limiter = TierRateLimiter()
        limiter.try_acquire("t", rate_override=-5.0)
        assert limiter.remaining("t") == pytest.approx(41.0, abs=0.1)


class TestRateLimitedDecorator:
    def test_raises_when_rate_limit_exceeded(self):
        import agent.tier_rate_limiter as trl

        trl.rate_limiter.reset_tier("decorated-tier")
        trl.rate_limiter._buckets["decorated-tier"] = _TokenBucket(rate_per_minute=1.0)

        @rate_limited(tier="decorated-tier")
        def dispatch():
            return "ok"

        assert dispatch() == "ok"
        with pytest.raises(RateLimitExceeded):
            dispatch()
        trl.rate_limiter.reset_tier("decorated-tier")

    def test_preserves_function_metadata(self):
        @rate_limited(tier="metadata-test")
        def my_function():
            """My docstring."""
            return 1

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."
