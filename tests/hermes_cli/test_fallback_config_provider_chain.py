"""Tests for the additive ``ProviderChain`` wiring in ``hermes_cli.fallback_config``.

``get_fallback_chain`` merges config into an ordered list of provider dicts
with no retry/backoff/metrics behavior. ``is_transient_fallback_error`` and
``build_fallback_provider_chain`` are new, opt-in helpers layered on top of
that same merged chain via ``agent.providers.ProviderChain`` — they do not
change ``get_fallback_chain`` itself or any existing call site.
"""

from __future__ import annotations

import pytest

from hermes_cli.fallback_config import (
    build_fallback_provider_chain,
    get_fallback_chain,
    is_transient_fallback_error,
)


def test_is_transient_fallback_error_matches_agent_providers_classifier():
    assert is_transient_fallback_error(RuntimeError("rate limit hit"))
    assert is_transient_fallback_error(TimeoutError("timed out"))
    assert not is_transient_fallback_error(ValueError("invalid api key"))


def test_get_fallback_chain_unchanged_by_new_helpers():
    config = {
        "fallback_providers": [
            {"provider": "openai", "model": "gpt-4o"},
            {"provider": "anthropic", "model": "claude"},
        ]
    }
    # Existing behavior is untouched: plain list of dict copies.
    chain = get_fallback_chain(config)
    assert chain == [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "anthropic", "model": "claude"},
    ]


def test_build_fallback_provider_chain_wraps_config_entries():
    config = {
        "fallback_providers": [
            {"provider": "p1", "model": "m1"},
            {"provider": "p2", "model": "m2"},
        ]
    }

    def flaky_then_ok(entry, prompt):
        if entry["provider"] == "p1":
            raise RuntimeError("503 server error")
        return f"{entry['provider']}:{prompt}"

    chain = build_fallback_provider_chain(
        config,
        flaky_then_ok,
        max_retries=1,
        base_delay_s=0.0,
    )
    chain.sleep = lambda _: None  # no real delays in the test

    result = chain.call("hello")

    assert result.provider == "p2"
    assert result.response == "p2:hello"
    assert chain.metrics.switches == 1
    assert chain.metrics.failures_per_provider == {"p1": 2}  # initial + 1 retry


def test_build_fallback_provider_chain_empty_config_raises_on_call():
    chain = build_fallback_provider_chain({}, lambda entry, prompt: prompt)
    with pytest.raises(RuntimeError):
        chain.call("x")
