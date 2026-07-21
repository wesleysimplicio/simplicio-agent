"""Focused tests for the deterministic watcher gate.

The fake callbacks deliberately exercise the comparison boundary only; they
are not evidence that a real external command or service was verified.
"""

import hashlib

import pytest

from tools.watcher_gate import (
    CommandObservation,
    ConsentRequiredError,
    EvidenceKind,
    RecursiveConsentError,
    Verdict,
    authorize_action,
    compare_reported_to_recomputed,
    has_explicit_consent,
    watch_command,
    watch_file,
    watch_hash,
    watch_result_boundary,
)


def test_verdicts_are_typed_and_have_stable_wire_values():
    assert Verdict.MEASURED.value == "MEASURED"
    assert isinstance(Verdict.CANON, str)
    assert {item.value for item in Verdict} == {
        "MEASURED",
        "CANON",
        "UNVERIFIED",
        "FABRICATED",
    }


def test_reported_and_recomputed_mapping_order_is_irrelevant():
    result = compare_reported_to_recomputed(
        {"b": 2, "a": [1, 3]},
        {"a": [1, 3], "b": 2},
    )

    assert result.verdict is Verdict.MEASURED
    assert result.matches is True
    assert result.passed is True


def test_mismatch_is_fabricated():
    result = compare_reported_to_recomputed({"count": 4}, {"count": 5})

    assert result.verdict is Verdict.FABRICATED
    assert result.matches is False
    assert result.passed is False


def test_canonical_source_gets_canon_verdict():
    result = compare_reported_to_recomputed("ok", "ok", source="canonical")

    assert result.verdict is Verdict.CANON
    assert result.status == "CANON"


def test_external_network_and_llm_sources_are_unverified_even_when_equal():
    for source in ("external", "network_api", "llm", "remote_model"):
        result = compare_reported_to_recomputed(1, 1, source=source)
        assert result.verdict is Verdict.UNVERIFIED
        assert result.matches is True
        assert result.passed is False


def test_consent_check_is_direct_and_non_recursive():
    assert has_explicit_consent(True) is True
    assert has_explicit_consent(False) is False
    assert has_explicit_consent({"consent": True}) is False
    assert has_explicit_consent([True]) is False
    assert has_explicit_consent("true") is False


def test_required_consent_blocks_before_comparison():
    result = compare_reported_to_recomputed(
        {"ok": True}, {"ok": True}, consent={"consent": True}, require_consent=True
    )

    assert result.verdict is Verdict.UNVERIFIED
    assert result.consented is False
    assert result.reported_canonical is None


def test_non_json_values_are_unverified():
    result = compare_reported_to_recomputed({"value": {1, 2}}, {"value": {1, 2}})

    assert result.verdict is Verdict.UNVERIFIED
    assert result.passed is False


def _file_claim(payload: bytes) -> dict[str, object]:
    return {
        "exists": True,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_file_match_is_measured(tmp_path):
    payload = b"trusted local fixture\n"
    (tmp_path / "receipt.txt").write_bytes(payload)

    result = watch_file(tmp_path, "receipt.txt", _file_claim(payload))

    assert result.verdict is Verdict.MEASURED
    assert result.passed


def test_file_injected_hash_is_caught_at_injection_point(tmp_path):
    payload = b"actual bytes\n"
    (tmp_path / "receipt.txt").write_bytes(payload)
    forged = _file_claim(payload)
    forged["sha256"] = "0" * 64

    result = watch_file(tmp_path, "receipt.txt", forged)

    assert result.kind is EvidenceKind.FILE
    assert result.verdict is Verdict.FABRICATED
    assert result.passed is False


def test_file_path_escape_is_unverified_not_a_fake_pass(tmp_path):
    result = watch_file(tmp_path, "../outside.txt", _file_claim(b"x"))

    assert result.verdict is Verdict.UNVERIFIED
    assert result.passed is False


def test_hash_injected_digest_is_caught_at_injection_point():
    result = watch_hash(b"actual", "f" * 64)

    assert result.kind is EvidenceKind.HASH
    assert result.verdict is Verdict.FABRICATED


def test_hash_match_uses_canonical_json():
    value = {"b": 2, "a": [1, True]}
    digest = hashlib.sha256(b'{"a":[1,true],"b":2}').hexdigest()

    result = watch_hash(value, {"algorithm": "SHA256", "digest": digest})

    assert result.verdict is Verdict.MEASURED
    assert result.passed


def test_command_forged_exit_code_is_caught_at_injection_point():
    reported = CommandObservation.from_output(0, "reported pass")
    actual = CommandObservation.from_output(1, "real failure")
    calls = 0

    def recompute():
        nonlocal calls
        calls += 1
        return actual

    result = watch_command("pytest tests/unit.py", reported, recompute)

    assert calls == 1
    assert result.verdict is Verdict.FABRICATED
    assert result.kind is EvidenceKind.COMMAND


def test_command_without_recompute_is_unverified():
    result = watch_command(
        "pytest tests/unit.py",
        CommandObservation.from_output(0, "pass"),
        None,
    )

    assert result.verdict is Verdict.UNVERIFIED
    assert not result.passed


def test_command_recompute_failure_is_unverified_not_fabricated():
    def recompute():
        raise RuntimeError("fake runner unavailable")

    result = watch_command(
        "pytest tests/unit.py",
        CommandObservation.from_output(0, "pass"),
        recompute,
    )

    assert result.verdict is Verdict.UNVERIFIED
    assert "failed" in result.reason


def test_result_boundary_without_recompute_is_unverified():
    result = watch_result_boundary(
        {"ok": True},
        None,
        kind="tool-result",
        subject="demo.tool",
    )

    assert result.verdict is Verdict.UNVERIFIED
    assert result.passed is False
    assert result.kind is EvidenceKind.RESULT


def test_result_boundary_recomputes_a_subagent_claim():
    result = watch_result_boundary(
        {"status": "completed", "summary": "tests pass"},
        lambda: {"status": "failed", "summary": "tests fail"},
        kind="sub-agent",
        subject="child-1",
    )

    assert result.verdict is Verdict.FABRICATED
    assert result.matches is False
    assert result.passed is False
    assert result.kind is EvidenceKind.SUB_AGENT


def test_only_depth_zero_operator_can_authorize():
    authorization = authorize_action(
        "publish", principal="operator", depth=0, consent=True
    )
    assert authorization.action == "publish"

    with pytest.raises(RecursiveConsentError):
        authorize_action("publish", principal="sub-agent", depth=1, consent=True)
    with pytest.raises(ConsentRequiredError):
        authorize_action("publish", principal="operator", consent=False)
