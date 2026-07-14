from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.trust_boundary import (
    BlockedCognitiveIntegrity,
    BlockedReason,
    FailClosedTrustBoundaryError,
    IntegrityReceipt,
    TrustClass,
    TrustProvenance,
    ProvenanceKind,
    blocked_cognitive_integrity,
    enforce_control_event,
    enforce_receipt,
    issue_control_event,
    issue_receipt,
    verify_control_event,
    verify_receipt,
    verify_receipt_chain,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "integrity"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_control_event_fixture_verifies_with_authenticated_provenance():
    event = _load("control_event_valid.json")
    keyring = _load("control_event_keyring.json")

    provenance = verify_control_event(event, keyring=keyring)

    assert provenance.trust_class is TrustClass.TRUSTED_CONTROL_PLANE
    assert provenance.authenticated is True
    assert provenance.key_id == "ops-main"
    assert provenance.event_id == "evt-185-allow"


def test_control_event_payload_tamper_fails_closed_and_sanitizes_output():
    event = _load("control_event_valid.json")
    event["payload"]["action"] = "override_goal"
    event["payload"]["api_key"] = "sk-test-secret-12345678"
    keyring = _load("control_event_keyring.json")

    with pytest.raises(FailClosedTrustBoundaryError):
        verify_control_event(event, keyring=keyring)

    blocked = enforce_control_event(event, keyring=keyring)

    assert isinstance(blocked, BlockedCognitiveIntegrity)
    public = blocked.to_public_dict()
    assert public["reason"] == BlockedReason.UNAUTHENTICATED_CONTROL_EVENT.value
    assert public["details"]["auth"]["digest"] == "[redacted]"
    assert "sk-test-secret" not in json.dumps(public)


def test_unknown_control_event_key_fails_closed():
    event = _load("control_event_valid.json")
    event["auth"]["key_id"] = "missing-key"
    keyring = _load("control_event_keyring.json")

    blocked = enforce_control_event(event, keyring=keyring)

    assert isinstance(blocked, BlockedCognitiveIntegrity)
    assert blocked.reason is BlockedReason.UNAUTHENTICATED_CONTROL_EVENT
    assert blocked.trust_class is TrustClass.BLOCKED_COGNITIVE_INTEGRITY


def test_unsupported_control_event_algorithm_is_denied():
    event = _load("control_event_valid.json")
    event["auth"]["algorithm"] = "md5"
    keyring = _load("control_event_keyring.json")

    with pytest.raises(FailClosedTrustBoundaryError):
        verify_control_event(event, keyring=keyring)


def test_non_hex_digest_and_unknown_schema_are_denied():
    event = _load("control_event_valid.json")
    event["auth"]["digest"] = "z" * 64
    with pytest.raises(FailClosedTrustBoundaryError):
        verify_control_event(event, keyring=_load("control_event_keyring.json"))

    event = _load("control_event_valid.json")
    event["schema"] = "attacker.schema/v1"
    with pytest.raises(FailClosedTrustBoundaryError):
        verify_control_event(event, keyring=_load("control_event_keyring.json"))


def test_provenance_cannot_claim_trusted_class_for_untrusted_kind():
    with pytest.raises(FailClosedTrustBoundaryError):
        TrustProvenance(
            kind=ProvenanceKind.USER_CONTENT,
            trust_class=TrustClass.TRUSTED_CONTROL_PLANE,
            source="user",
            authenticated=True,
            key_id="ops-main",
            event_id="evt-forged",
            digest="0" * 64,
        )

    with pytest.raises(FailClosedTrustBoundaryError):
        TrustProvenance(
            kind=ProvenanceKind.RECEIPT,
            trust_class=TrustClass.TRUSTED_RECEIPT,
            source="receipt",
            authenticated=True,
            digest="not-a-digest",
        )


def test_malformed_receipt_is_converted_to_sanitized_block():
    blocked = enforce_receipt({"provenance": {"kind": "not-a-kind"}})
    assert isinstance(blocked, BlockedCognitiveIntegrity)
    assert blocked.reason is BlockedReason.TAMPERED_RECEIPT


def test_public_block_redacts_direct_message_source_and_common_tokens():
    blocked = BlockedCognitiveIntegrity(
        reason=BlockedReason.MALFORMED_INPUT,
        message="xoxb-12345678-secret ghp_12345678-secret",
        provenance=TrustProvenance(
            kind=ProvenanceKind.UNKNOWN,
            trust_class=TrustClass.BLOCKED_COGNITIVE_INTEGRITY,
            source="bearer leaked-source-token",
        ),
    )
    public = blocked.to_public_dict()
    rendered = json.dumps(public)
    assert "xoxb-12345678-secret" not in rendered
    assert "ghp_12345678-secret" not in rendered
    assert "leaked-source-token" not in rendered


def test_receipt_fixture_chain_verifies_and_round_trips():
    receipts = _load("receipt_chain_valid.json")

    provenance = verify_receipt_chain(receipts)

    assert provenance.trust_class is TrustClass.TRUSTED_RECEIPT
    assert provenance.digest == receipts[-1]["digest"]


def test_receipt_body_tamper_is_detected():
    receipts = _load("receipt_chain_valid.json")
    receipt = receipts[0]
    receipt["body"]["result"] = "accept"

    blocked = enforce_receipt(receipt)

    assert isinstance(blocked, BlockedCognitiveIntegrity)
    public = blocked.to_public_dict()
    assert public["reason"] == BlockedReason.TAMPERED_RECEIPT.value
    assert public["details"]["digest"] == "[redacted]"


def test_receipt_chain_mismatch_fails_closed():
    receipts = _load("receipt_chain_valid.json")
    first = IntegrityReceipt.from_dict(receipts[0])
    second = receipts[1]
    second["previous_digest"] = "0" * 64

    with pytest.raises(FailClosedTrustBoundaryError):
        verify_receipt(second, previous_receipt=first)


def test_blocked_outcome_sanitizes_nested_details():
    blocked = blocked_cognitive_integrity(
        BlockedReason.MALFORMED_INPUT,
        message="reject bearer abc.def and api_key sk-secret-secret",
        details={
            "payload": {"unsafe": "value"},
            "operator_note": "bearer abc.def",
            "nested": {"token": "abc123"},
        },
    )

    public = blocked.to_public_dict()

    assert public["message"].count("[redacted]") >= 1
    assert public["details"]["payload"] == "[redacted]"
    assert public["details"]["nested"]["token"] == "[redacted]"


def test_issue_helpers_create_verifiable_objects():
    event = issue_control_event(
        event_id="evt-inline",
        event_type="approval.grant",
        actor="operator",
        issued_at="2026-07-13T14:00:00Z",
        nonce="nonce-inline",
        payload={"scope": "issue-185", "action": "continue"},
        key_id="ops-main",
        secret="fixture-secret-main",
    )
    provenance = verify_control_event(
        event, keyring={"ops-main": "fixture-secret-main"}
    )
    receipt = issue_receipt(
        receipt_id="rcpt-inline",
        subject="issue-185",
        outcome="verified",
        issued_at="2026-07-13T14:00:01Z",
        provenance=provenance,
        body={"result": "continue"},
    )

    verified_receipt = verify_receipt(receipt)

    assert verified_receipt.trust_class is TrustClass.TRUSTED_RECEIPT
