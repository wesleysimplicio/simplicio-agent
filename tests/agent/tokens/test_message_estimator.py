"""Tests for agent/tokens/message_estimator.py (issue #111).

Core AC: image-token-cost semantics must be preserved EXACTLY relative to
agent.model_metadata.estimate_messages_tokens_rough — a screenshot must
always cost the flat ~1500-token image rate, never raw base64 char length.
"""

from agent.model_metadata import estimate_messages_tokens_rough
from agent.tokens.message_estimator import estimate_messages_tokens_fast, _message_text_parts


def _image_message(base64_len: int) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + ("A" * base64_len)}},
        ],
    }


class TestImageTokenCostPreservedExactly:
    def test_single_image_costs_flat_1500_not_raw_base64_length(self):
        # A 1MB-ish screenshot (per the rough estimator's own docstring
        # warning: "a single ~1MB screenshot would be estimated at ~250K
        # tokens" without the special case).
        msg = _image_message(base64_len=1_000_000)
        result = estimate_messages_tokens_fast([msg])
        # Must be small (image flat cost + a few text tokens), NOT ~250,000.
        assert result < 2000, f"image cost leaked raw base64 length: got {result}"

    def test_image_token_contribution_matches_rough_estimator_exactly(self):
        """The image-counting helper itself is SHARED (imported, not
        reimplemented) between the two estimators, so it must return the
        identical value for the identical message regardless of image
        payload size — the precise form of "preserved exactly"."""
        from agent.model_metadata import _count_image_tokens as rough_count_image_tokens
        from agent.tokens.message_estimator import _count_image_tokens as fast_count_image_tokens

        assert rough_count_image_tokens is fast_count_image_tokens

        for base64_len in (10, 500, 1_000_000):
            msg = _image_message(base64_len=base64_len)
            assert rough_count_image_tokens(msg, 1500) == 1500
            assert fast_count_image_tokens(msg, 1500) == 1500

    def test_multiple_images_scale_linearly_by_flat_cost(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 200}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "B" * 200}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "C" * 200}},
            ],
        }
        no_image_baseline = estimate_messages_tokens_fast([{"role": "user", "content": ""}])
        result = estimate_messages_tokens_fast([msg])
        assert result - no_image_baseline == 3 * 1500

    def test_anthropic_stashed_content_blocks_also_counted(self):
        msg = {
            "role": "user",
            "content": "text only",
            "_anthropic_content_blocks": [{"type": "image", "source": {"data": "x" * 100}}],
        }
        result = estimate_messages_tokens_fast([msg])
        baseline = estimate_messages_tokens_fast([{"role": "user", "content": "text only"}])
        assert result - baseline == 1500


class TestTextEstimation:
    def test_estimate_is_nonzero_for_real_text(self):
        msgs = [{"role": "user", "content": "hello world, this is a test"}]
        assert estimate_messages_tokens_fast(msgs) > 0

    def test_empty_messages_list_is_zero(self):
        assert estimate_messages_tokens_fast([]) == 0

    def test_non_dict_message_does_not_crash(self):
        # Defensive: malformed input should degrade, not raise.
        result = estimate_messages_tokens_fast(["not a dict"])  # type: ignore[list-item]
        assert result >= 0

    def test_message_text_parts_extracts_role_and_string_content(self):
        parts = _message_text_parts({"role": "assistant", "content": "hi there"})
        assert "assistant" in parts
        assert "hi there" in parts

    def test_message_text_parts_handles_list_content_with_dicts(self):
        msg = {
            "role": "tool",
            "content": [{"type": "text", "text": "result text"}, "raw string part"],
        }
        parts = _message_text_parts(msg)
        assert "result text" in parts
        assert "raw string part" in parts
        assert "tool" in parts


class TestFasterThanRoughInThisEnvironment:
    """Not a hard perf gate (too environment-sensitive for CI) — just a
    smoke check that the new estimator isn't wildly slower than the one it
    may replace, backed by the real numbers in scripts/bench_token_estimators.py."""

    def test_produces_a_result_for_a_1000_message_history(self):
        import time

        messages = [{"role": "user", "content": "x" * 200} for _ in range(1000)]
        t0 = time.perf_counter()
        result = estimate_messages_tokens_fast(messages)
        elapsed = time.perf_counter() - t0
        assert result > 0
        assert elapsed < 1.0, f"1000-message estimate took {elapsed:.3f}s, too slow for a pre-flight check"
