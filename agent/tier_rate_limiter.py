"""Per-tier token-bucket rate limiter for subagent dispatch.

Provides a thread-safe, per-tier token-bucket rate limiter backed by
environment variable configuration. Each tier gets its own bucket with
configurable tokens/minute rate. Designed for use before dispatching
subagents to prevent overwhelming backend services.

Usage::

    from agent.tier_rate_limiter import rate_limiter

    if rate_limiter.try_acquire("research"):
        # dispatch subagent
    else:
        # reject or queue

Or as a decorator::

    @rate_limited(tier="research")
    def dispatch_subagent() -> dict:
        ...
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

_DEFAULT_RATE_PER_MINUTE: float = 60.0
_ENV_PREFIX: str = "HERMES_TIER_RATE_LIMIT_"

F = TypeVar("F", bound=Callable[..., object])


class _TokenBucket:
    """Token bucket for a single tier.

    Classic token-bucket algorithm: tokens accumulate at a fixed
    refill rate up to a maximum capacity.  ``try_consume`` draws from
    the bucket and returns ``True`` only when sufficient tokens are
    available.
    """

    __slots__ = ("capacity", "refill_per_second", "tokens", "last_refill")

    def __init__(self, rate_per_minute: float) -> None:
        self.capacity: float = rate_per_minute
        self.refill_per_second: float = rate_per_minute / 60.0
        # Start full so the first dispatch in a fresh session is never
        # penalised by an empty bucket.
        self.tokens: float = rate_per_minute
        self.last_refill: float = time.monotonic()

    def refill(self) -> None:
        """Top up tokens based on elapsed wall-clock time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            added = elapsed * self.refill_per_second
            self.tokens = min(self.capacity, self.tokens + added)
            self.last_refill = now

    def try_consume(self, tokens: float = 1.0) -> bool:
        """Try to consume *tokens* from the bucket.

        Returns ``True`` if the tokens were deducted (caller should
        proceed).  Returns ``False`` when the bucket is too low.
        """
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class TierRateLimiter:
    """Thread-safe per-tier token-bucket rate limiter.

    Each tier is configured via an environment variable named
    ``HERMES_TIER_RATE_LIMIT_<TIER>`` (where *tier* is uppercased)
    whose value is the number of tokens **per minute** the tier is
    allowed.  If the variable is absent the tier defaults to **60
    tokens/minute**.

    Config is re-read from the environment on every *new* bucket
    creation, so changing env vars at runtime will affect tiers that
    haven't been seen yet.  Already-created buckets keep their
    original rate until they are explicitly reset.

    Thread-safety is provided by a single ``threading.Lock`` that
    guards both the bucket dict and each bucket's mutations.  The
    lock is held for the entire ``try_acquire`` call so that refill
    and consume are atomic per tier.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, _TokenBucket] = {}

    def _get_rate_for_tier(self, tier: str) -> float:
        """Read the tokens/minute from the environment for *tier*.

        Falls back to ``_DEFAULT_RATE_PER_MINUTE`` (60) when the env
        var is absent, empty, unparseable, or non-positive.
        """
        env_key = f"{_ENV_PREFIX}{tier.upper()}"
        raw = os.environ.get(env_key)
        if raw is not None:
            stripped = raw.strip()
            if stripped:
                try:
                    val = float(stripped)
                    if val > 0:
                        return val
                    logger.warning(
                        "Rate limit for tier %r is non-positive (%r=%s); "
                        "falling back to default %d/min",
                        tier, env_key, stripped, _DEFAULT_RATE_PER_MINUTE,
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        "Could not parse rate for tier %r from %r=%r; "
                        "falling back to default %d/min",
                        tier, env_key, stripped, _DEFAULT_RATE_PER_MINUTE,
                    )
        return _DEFAULT_RATE_PER_MINUTE

    def try_acquire(self, tier: str, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the bucket for *tier*.

        Returns ``True`` when the tokens were consumed and the caller
        should proceed with dispatching.  Returns ``False`` when the
        bucket is depleted.

        The bucket is **lazy-created** on first access — if no bucket
        exists for the tier yet, the rate is freshly read from the
        environment at that point.

        Thread-safe.
        """
        if tokens <= 0:
            return True  # degenerate case — nothing to consume

        with self._lock:
            bucket = self._buckets.get(tier)
            if bucket is None:
                rate = self._get_rate_for_tier(tier)
                bucket = _TokenBucket(rate)
                self._buckets[tier] = bucket
                logger.debug(
                    "Created rate-limit bucket for tier %r: %d tokens/min",
                    tier, int(rate),
                )
            return bucket.try_consume(float(tokens))

    def remaining(self, tier: str) -> float:
        """Return the approximate number of tokens remaining for *tier*.

        Returns the full capacity when the tier has never been used.
        The value includes any tokens accrued since the last consume
        (via the refill mechanism).
        """
        with self._lock:
            bucket = self._buckets.get(tier)
            if bucket is None:
                return self._get_rate_for_tier(tier)
            bucket.refill()
            return bucket.tokens

    def reset_tier(self, tier: str) -> None:
        """Reset the bucket for *tier* to full capacity."""
        with self._lock:
            self._buckets.pop(tier, None)

    def reset_all(self) -> None:
        """Reset all tier buckets to full capacity."""
        with self._lock:
            self._buckets.clear()


# Singleton — import and use anywhere in the process.
rate_limiter: TierRateLimiter = TierRateLimiter()


class RateLimitExceeded(Exception):
    """Raised when a ``@rate_limited`` decorated function cannot dispatch.

    Attributes:
        tier: The tier that was rate-limited.
        remaining: Approximate tokens remaining in the bucket.
    """

    def __init__(self, tier: str, remaining: float = 0.0) -> None:
        self.tier = tier
        self.remaining = remaining
        super().__init__(
            f"Rate limit exceeded for tier {tier!r}. "
            f"Remaining tokens: {remaining:.1f}. "
            f"Try again later or increase "
            f"{_ENV_PREFIX}{tier.upper()}."
        )


def rate_limited(tier: str) -> Callable[[F], F]:
    """Decorator that checks the rate limiter before calling the wrapped function.

    Usage::

        @rate_limited(tier="research")
        def my_subagent_dispatch() -> dict:
            ...

    If the rate limiter denies the request, a :class:`RateLimitExceeded`
    exception is raised so the caller can catch and handle it (e.g. fall
    back to a slower path or queue the work).
    """

    def decorator(func: F) -> F:
        def wrapper(*args: object, **kwargs: object) -> object:
            if not rate_limiter.try_acquire(tier):
                raise RateLimitExceeded(
                    tier, remaining=rate_limiter.remaining(tier),
                )
            return func(*args, **kwargs)

        # Preserve function metadata
        wrapper.__name__ = func.__name__
        wrapper.__qualname__ = func.__qualname__
        wrapper.__doc__ = func.__doc__
        wrapper.__module__ = func.__module__
        wrapper.__dict__.update(func.__dict__)

        return wrapper  # type: ignore[return-value]

    return decorator
