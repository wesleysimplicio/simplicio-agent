from __future__ import annotations

import pytest

from agent.delivery_certificate import (
    CertificateLedger,
    CertificateStatus,
    EvidenceVerdict,
    ReproducibleManifest,
    RoutingDecision,
    StructuralCheck,
    TaskCertificate,
    sha256_text,
    verify_ledger,
)


def _manifest(
    *, runtime_available: bool = False, runtime_certificate_claim: bool = False
):
    return ReproducibleManifest(
        task_id="task-24",
        agent_version="agent-test",
        runtime_version="3.5.0" if runtime_available else None,
        runtime_available=runtime_available,
        provider="test-provider",
        model="test-model",
        temperature=0.0,
        seed=24,
        prompt_sha256=sha256_text("prompt"),
        trajectory_sha256=sha256_text("trajectory"),
        diff_sha256=sha256_text("diff"),
        routing=RoutingDecision.NO_THINK,
        runtime_certificate_claim=runtime_certificate_claim,
    )


def _check(name: str = "structural"):
    return StructuralCheck(name, True, "checked from deterministic local facts")


def _evidence(name: str = "tests", *, recomputed: str | None = "passed"):
    return EvidenceVerdict(
        name=name,
        reference=f"receipt://{name}",
        reported="passed",
        recomputed=recomputed,
    )


def test_happy_path_certificate_is_typed_reproducible_and_round_trips():
    certificate = TaskCertificate.create(
        task_id="task-24",
        manifest=_manifest(),
        evidence=(_evidence(),),
        structural_checks=(_check(),),
    )

    assert isinstance(certificate, TaskCertificate)
    assert certificate.status is CertificateStatus.PASSED
    assert certificate.is_verified
    assert certificate.verify().to_dict() == {
        "valid": True,
        "verdict": "passed",
        "reasons": [],
    }
    assert (
        certificate.canonical_json()
        == TaskCertificate.from_dict(certificate.to_dict()).canonical_json()
    )
    assert certificate.manifest.routing == RoutingDecision.NO_THINK
    assert certificate.manifest.runtime_certificate_claim is False
    assert certificate.signing_status == "not_claimed"


def test_missing_recomputation_is_unverified_and_structural_failure_is_not_hidden():
    certificate = TaskCertificate.create(
        task_id="task-24",
        manifest=_manifest(),
        evidence=(_evidence(recomputed=None),),
        structural_checks=(
            StructuralCheck("anti-fake", False, "placeholder rejected"),
        ),
    )

    assert certificate.status is CertificateStatus.UNVERIFIED
    assert not certificate.is_verified
    assert "not deterministically verified" in certificate.reason
    assert "structural check 'anti-fake' failed" in certificate.reason


def test_explicit_block_is_a_valid_blocked_certificate_without_done_claim():
    certificate = TaskCertificate.create(
        task_id="task-24",
        manifest=_manifest(),
        evidence=(),
        structural_checks=(_check(),),
        blocked_reason="Simplicio Runtime attestation is unavailable",
    )

    assert certificate.status is CertificateStatus.BLOCKED
    assert certificate.verify().valid
    assert certificate.is_verified is False
    assert certificate["status"] == "blocked"
    assert "attestation" in certificate["reason"]


def test_runtime_certificate_claim_is_rejected_when_runtime_is_unavailable():
    with pytest.raises(ValueError, match="runtime certificate"):
        _manifest(runtime_certificate_claim=True)


def test_hash_linked_ledger_verifies_and_detects_tampering():
    ledger = CertificateLedger()
    first = TaskCertificate.create(
        task_id="task-24",
        manifest=_manifest(),
        evidence=(_evidence("first"),),
        structural_checks=(_check("first-check"),),
    )
    second = TaskCertificate.create(
        task_id="task-25",
        manifest=ReproducibleManifest(**{
            **_manifest().to_dict(),
            "task_id": "task-25",
        }),
        evidence=(_evidence("second"),),
        structural_checks=(_check("second-check"),),
    )

    first_entry = ledger.append(first)
    second_entry = ledger.append(second)
    assert first_entry.previous_hash == "0" * 64
    assert second_entry.previous_hash == first_entry.entry_hash
    assert ledger.verify().valid

    tampered = ledger.to_list()
    tampered[0]["certificate"]["status"] = "blocked"
    result = verify_ledger(tampered)
    assert result.valid is False
    assert result.entries_checked == 2
    assert any("certificate hash" in reason for reason in result.reasons)


def test_ledger_detects_broken_link_even_when_entry_payload_is_unchanged():
    ledger = CertificateLedger()
    certificate = TaskCertificate.create(
        task_id="task-24",
        manifest=_manifest(),
        evidence=(_evidence(),),
        structural_checks=(_check(),),
    )
    ledger.append(certificate)
    tampered = ledger.to_list()
    tampered.append({**tampered[0], "sequence": 1, "previous_hash": "f" * 64})

    result = verify_ledger(tampered)
    assert result.valid is False
    assert any("previous-hash link" in reason for reason in result.reasons)
