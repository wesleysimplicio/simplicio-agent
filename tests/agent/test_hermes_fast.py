import pytest

import agent._hermes_fast as hermes_fast
from agent._hermes_fast import (
    HAVE_RUST,
    estimate_messages_tokens,
    estimate_tokens,
    estimate_tokens_many,
    parse_tool_call_delta,
    truncate_messages_to_limit,
)


class _SentinelRust:
    """Stand-in for the loaded Rust extension that flags which path ran.

    Every routed call returns an obviously-wrong value so a test can assert
    whether the Rust branch was taken (sentinel returned) or the Python
    fallback was used (correct value returned).
    """

    SENTINEL_INT = -424242

    def estimate_tokens(self, text):  # noqa: ARG002
        return self.SENTINEL_INT

    def estimate_tokens_many(self, texts):
        return [self.SENTINEL_INT] * len(texts)

    def estimate_messages_tokens(self, encoded):  # noqa: ARG002
        return self.SENTINEL_INT

    def truncate_messages_to_limit(self, encoded, max_tokens):  # noqa: ARG002
        return b"[]"

    def parse_tool_call_delta(self, buf):  # noqa: ARG002
        return (True, {"sentinel": True}, len(buf))


def test_estimate_tokens_many_matches_scalar_estimator():
    texts = ["", "a", "abcd", "abcde", "hello world"]

    assert estimate_tokens_many(texts) == [estimate_tokens(text) for text in texts]


def test_estimate_messages_tokens_counts_message_roles_and_content():
    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "abcdefgh"},
    ]

    expected = (
        estimate_tokens("system")
        + estimate_tokens("abcd")
        + 4
        + estimate_tokens("user")
        + estimate_tokens("abcdefgh")
        + 4
    )
    assert estimate_messages_tokens(messages) == expected


def test_truncate_messages_to_limit_uses_message_token_budget():
    system = {"role": "system", "content": "keep"}
    drop = {"role": "user", "content": "x" * 80}
    tail = {"role": "assistant", "content": "keep"}
    limit = estimate_messages_tokens([system, tail])

    assert truncate_messages_to_limit([system, drop, tail], limit) == [system, tail]


def test_parse_tool_call_delta_handles_nested_tool_payloads():
    payload = (
        ' {"id":"tc_1","function":{"name":"search","arguments":"{\\"q\\":true}"},'
        '"items":[1,2.5,null],"ok":true} trailing'
    )

    ok, value, consumed = parse_tool_call_delta(payload)

    assert ok is True
    assert value["function"]["name"] == "search"
    assert value["function"]["arguments"] == '{"q":true}'
    assert value["items"] == [1, 2.5, None]
    assert value["ok"] is True
    assert payload[consumed:] == " trailing"


def test_estimates_stay_on_python_even_when_extension_present(monkeypatch):
    """Default policy: estimation/truncation must NOT route through Rust.

    Measured boundary cost makes Rust a net loss for these ops, so with the
    extension loaded but the opt-in flag off, the pure-Python path runs.
    """
    monkeypatch.setattr(hermes_fast, "_rust", _SentinelRust())
    monkeypatch.setattr(hermes_fast, "_USE_RUST_ESTIMATES", False)

    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "abcdefgh"},
    ]
    # If Rust had been used, every result would be the sentinel value.
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens_many(["abcd", "abcdefgh"]) == [1, 2]
    assert estimate_messages_tokens(messages) > 0
    assert estimate_messages_tokens(messages) != _SentinelRust.SENTINEL_INT
    keep = {"role": "system", "content": "k"}
    drop = {"role": "user", "content": "x" * 80}
    tail = {"role": "assistant", "content": "k"}
    limit = estimate_messages_tokens([keep, tail])
    assert truncate_messages_to_limit([keep, drop, tail], limit) == [keep, tail]


def test_parse_tool_call_delta_routes_through_extension_when_present(monkeypatch):
    """parse_tool_call_delta is the one op that always prefers Rust (~3x win)."""
    monkeypatch.setattr(hermes_fast, "_rust", _SentinelRust())
    # The opt-in flag is irrelevant for delta parsing.
    monkeypatch.setattr(hermes_fast, "_USE_RUST_ESTIMATES", False)

    ok, value, consumed = parse_tool_call_delta('{"a":1}')
    assert ok is True
    assert value == {"sentinel": True}


def test_rust_estimates_flag_opts_back_into_rust(monkeypatch):
    """HERMES_RUST_ESTIMATES=1 restores the Rust path for estimates."""
    monkeypatch.setattr(hermes_fast, "_rust", _SentinelRust())
    monkeypatch.setattr(hermes_fast, "_USE_RUST_ESTIMATES", True)

    assert estimate_tokens("abcd") == _SentinelRust.SENTINEL_INT
    assert estimate_messages_tokens([{"role": "user", "content": "x"}]) == (
        _SentinelRust.SENTINEL_INT
    )


# ---------------------------------------------------------------------------
# Real compiled-extension coverage (issue #113).
#
# Every test above stubs ``hermes_fast._rust`` with ``_SentinelRust`` — it
# proves *dispatch* (which branch ran) but never proves the real PyO3
# extension returns correct data, because CI never had the extension built.
# These tests exercise the actual ``hermes_fast`` native module and are
# skipped (not failed) when it isn't importable, so this file still passes
# unmodified on a source-only/no-Rust-toolchain install — the release CI
# job that builds the maturin wheel (`.github/workflows/release.yml`,
# `build-rust-ext-wheel`) is what turns these from skipped to executed.
# ---------------------------------------------------------------------------

requires_rust_extension = pytest.mark.skipif(
    not HAVE_RUST,
    reason="hermes_fast native extension not installed (build rust_ext/ with maturin)",
)


@requires_rust_extension
def test_real_extension_parse_tool_call_delta_matches_python_fallback():
    payload = (
        ' {"id":"tc_1","function":{"name":"search","arguments":"{\\"q\\":true}"},'
        '"items":[1,2.5,null],"ok":true} trailing'
    )

    ok, value, consumed = parse_tool_call_delta(payload)

    assert ok is True
    assert value["function"]["name"] == "search"
    assert value["function"]["arguments"] == '{"q":true}'
    assert value["items"] == [1, 2.5, None]
    assert value["ok"] is True
    assert payload[consumed:] == " trailing"


@requires_rust_extension
def test_real_extension_parse_tool_call_delta_handles_incomplete_buffer():
    ok, value, consumed = parse_tool_call_delta("   ")
    assert ok is False
    assert value is None
    assert consumed == 0

    ok, value, consumed = parse_tool_call_delta('{"a": 1')
    assert ok is False
    assert value is None
    assert consumed == 0


@requires_rust_extension
def test_real_extension_estimates_match_python_when_opted_in(monkeypatch):
    """With HERMES_RUST_ESTIMATES=1 and the real extension, results must
    still match the pure-Python semantics exactly — the Rust path is a
    performance optimization, not a behavior change."""
    monkeypatch.setattr(hermes_fast, "_USE_RUST_ESTIMATES", True)
    assert hermes_fast._rust_estimates_active() is True

    texts = ["", "a", "abcd", "abcde", "hello world"]
    expected = [hermes_fast._estimate_tokens_local(t) for t in texts]
    assert [estimate_tokens(t) for t in texts] == expected
    assert estimate_tokens_many(texts) == expected

    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "abcdefgh"},
    ]
    expected_total = sum(hermes_fast._py_message_cost(m) for m in messages)
    assert estimate_messages_tokens(messages) == expected_total

    system = {"role": "system", "content": "keep"}
    drop = {"role": "user", "content": "x" * 80}
    tail = {"role": "assistant", "content": "keep"}
    limit = sum(hermes_fast._py_message_cost(m) for m in (system, tail))
    assert truncate_messages_to_limit([system, drop, tail], limit) == [system, tail]
