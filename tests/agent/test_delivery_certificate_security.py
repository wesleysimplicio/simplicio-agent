from __future__ import annotations

import json

from agent.delivery_certificate import (
    CertificateLedger,
    Ed25519Signer,
    EvidenceVerdict,
    ReproducibleManifest,
    ReplayVerification,
    RoutingDecision,
    SignedLedgerStore,
    StructuralCheck,
    TaskCertificate,
    sha256_text,
    verify_ledger,
    verify_ledger_file,
    verify_replay,
)


def _certificate(task_id: str = "task-24") -> TaskCertificate:
    manifest = ReproducibleManifest(
        task_id=task_id,
        agent_version="agent-test",
        runtime_version="1.6.4",
        runtime_available=True,
        provider="test-provider",
        model="test-model",
        temperature=0.0,
        seed=24,
        prompt_sha256=sha256_text("prompt"),
        trajectory_sha256=sha256_text("trajectory"),
        diff_sha256=sha256_text("diff"),
        routing=RoutingDecision.NO_THINK,
    )
    return TaskCertificate.create(
        task_id=task_id,
        manifest=manifest,
        evidence=(EvidenceVerdict("tests", "receipt://tests", "passed", "passed"),),
        structural_checks=(StructuralCheck("anti-fake", True, "scanner passed"),),
    )


def test_signed_ledger_verifies_and_rejects_certificate_tampering():
    signer = Ed25519Signer.generate("operator-test")
    ledger = CertificateLedger(signer=signer, require_signatures=True)
    entry = ledger.append(_certificate())

    assert entry.signature
    assert entry.signer_id == "operator-test"
    assert verify_ledger(ledger.to_list(), require_signatures=True).valid

    tampered = ledger.to_list()
    tampered[0]["certificate"]["status"] = "blocked"
    result = verify_ledger(tampered, require_signatures=True)
    assert result.valid is False
    assert any("certificate hash" in reason for reason in result.reasons)
    assert any("signature" in reason for reason in result.reasons)


def test_signed_ledger_store_is_durable_and_verify_ledger_detects_line_tampering(
    tmp_path,
):
    signer = Ed25519Signer.generate("operator-test")
    path = tmp_path / "delivery-ledger.jsonl"
    store = SignedLedgerStore(path, signer)
    store.append(_certificate())
    store.append(_certificate("task-25"))

    assert verify_ledger_file(path).valid
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["task_id"] = "tampered-task"
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")

    result = verify_ledger_file(path)
    assert result.valid is False
    assert any(
        "signature" in reason or "task_id" in reason for reason in result.reasons
    )


def test_replay_requires_byte_equal_diff_or_explicit_nondeterminism_reason():
    manifest = _certificate().manifest
    equal = verify_replay(manifest, "diff")
    assert equal == ReplayVerification(True, True, False, ())

    mismatch = verify_replay(manifest, "different")
    assert mismatch.valid is False
    assert mismatch.byte_equal is False
    assert mismatch.explained is False

    explained_manifest = ReproducibleManifest(**{
        **manifest.to_dict(),
        "nondeterminism_reason": "provider sampling",
    })
    explained = verify_replay(explained_manifest, "different")
    assert explained == ReplayVerification(True, False, True, ("provider sampling",))
