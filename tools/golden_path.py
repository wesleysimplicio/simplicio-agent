"""Build and verify a bounded request-to-delivery receipt.

The existing ``agent.golden_path`` harness proves the fixture operation path.
This module owns the smaller audit boundary: it turns one completed harness
result into a portable receipt and refuses claims that the fixture run was a
clean-machine end-to-end test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


GOLDEN_PATH_RECEIPT_SCHEMA = "simplicio-agent/issue-211-golden-path-receipt/v1"


class GoldenPathReceiptError(ValueError):
    """Raised when a request-to-delivery receipt is incomplete or tampered."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _transport_operations(result: Any) -> dict[str, dict[str, Any]]:
    receipts = _field(result, "transport_receipts", {}) or {}
    if not isinstance(receipts, Mapping):
        raise GoldenPathReceiptError("transport_receipts must be a mapping")
    operations: dict[str, dict[str, Any]] = {}
    for name in sorted(receipts):
        receipt = receipts[name]
        operations[str(name)] = {
            "ok": bool(_field(receipt, "ok", False)),
            "transport": _field(receipt, "transport"),
            "fallback_reason": _field(receipt, "fallback_reason"),
        }
    return operations


def build_request_delivery_receipt(result: Any) -> dict[str, Any]:
    """Return a canonical, fixture-scoped receipt for a completed run.

    ``result`` is intentionally duck-typed so this audit layer does not add a
    dependency from ``tools`` back to the harness implementation.  Transport
    request ids, timings, and payloads are omitted because they are runtime
    noise; the receipt records only the deterministic proof-bearing fields.
    """

    envelope = _field(result, "envelope")
    if envelope is None:
        raise GoldenPathReceiptError("result has no envelope")
    state = _field(envelope, "state")
    state = _field(state, "value", state)
    if state != "closed":
        raise GoldenPathReceiptError("request is not closed")

    evidence_refs = list(_field(envelope, "evidence_refs", ()) or ())
    if not evidence_refs:
        raise GoldenPathReceiptError("closed request has no evidence_refs")

    requery = _field(result, "requery", {}) or {}
    if not bool(_field(requery, "matches_expected", False)):
        raise GoldenPathReceiptError("independent final-state requery did not pass")

    operations = _transport_operations(result)
    for name, operation in operations.items():
        if operation["ok"] is not True:
            raise GoldenPathReceiptError(f"transport operation failed: {name}")
    delivery = operations.get("delivery")
    if delivery is None:
        raise GoldenPathReceiptError("delivery operation is missing")
    delivery_receipt = (_field(result, "transport_receipts", {}) or {}).get("delivery")
    if _field(_field(delivery_receipt, "value", {}), "accepted", False) is not True:
        raise GoldenPathReceiptError("delivery acknowledgment was not accepted")

    scenario = _field(result, "scenario")
    target = _field(envelope, "delivery_target") or _field(scenario, "delivery_target")
    if not target:
        raise GoldenPathReceiptError("delivery target is missing")

    payload: dict[str, Any] = {
        "schema": GOLDEN_PATH_RECEIPT_SCHEMA,
        "proof": {
            "scope": "fixture_only",
            "clean_machine_e2e": "not_claimed",
            "external_services": False,
        },
        "request": {
            "task_id": _field(envelope, "task_id"),
            "correlation_id": _field(envelope, "correlation_id"),
            "repo": _field(envelope, "repo"),
            "branch": _field(envelope, "branch"),
            "scope": _field(envelope, "scope"),
            "acceptance_criteria": list(
                _field(envelope, "acceptance_criteria", ()) or ()
            ),
            "write_set": list(_field(envelope, "write_set", ()) or ()),
        },
        "lifecycle": {
            "state": "closed",
            "evidence_refs": evidence_refs,
        },
        "mutation": {
            "write_set": list(_field(requery, "write_set", ()) or ()),
            "final_state": dict(_field(result, "final_state", {}) or {}),
            "requery_matches_expected": True,
        },
        "transport": {"operations": operations},
        "delivery": {
            "accepted": True,
            "target": target,
            "receipt_ref": _field(_field(result, "receipt_refs", {}) or {}, "delivery"),
        },
    }
    payload["receipt_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def verify_request_delivery_receipt(receipt: Mapping[str, Any]) -> bool:
    """Verify hash, proof scope, and close-gate invariants of a receipt."""

    if not isinstance(receipt, Mapping):
        raise GoldenPathReceiptError("receipt must be a mapping")
    observed_hash = receipt.get("receipt_sha256")
    if not isinstance(observed_hash, str):
        raise GoldenPathReceiptError("receipt_sha256 is missing")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    expected_hash = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    if observed_hash != expected_hash:
        raise GoldenPathReceiptError("receipt_sha256 does not match canonical payload")
    if receipt.get("schema") != GOLDEN_PATH_RECEIPT_SCHEMA:
        raise GoldenPathReceiptError("unsupported golden-path receipt schema")
    proof = receipt.get("proof")
    if not isinstance(proof, Mapping) or proof.get("scope") != "fixture_only":
        raise GoldenPathReceiptError("receipt proof scope must be fixture_only")
    if proof.get("clean_machine_e2e") != "not_claimed":
        raise GoldenPathReceiptError("clean-machine E2E claims are not valid here")
    lifecycle = receipt.get("lifecycle")
    if not isinstance(lifecycle, Mapping) or lifecycle.get("state") != "closed":
        raise GoldenPathReceiptError("receipt lifecycle is not closed")
    if not lifecycle.get("evidence_refs"):
        raise GoldenPathReceiptError("receipt has no evidence_refs")
    mutation = receipt.get("mutation")
    if (
        not isinstance(mutation, Mapping)
        or mutation.get("requery_matches_expected") is not True
    ):
        raise GoldenPathReceiptError("receipt lacks a passing independent requery")
    delivery = receipt.get("delivery")
    if not isinstance(delivery, Mapping) or delivery.get("accepted") is not True:
        raise GoldenPathReceiptError("delivery was not accepted")
    transport = receipt.get("transport")
    operations = transport.get("operations") if isinstance(transport, Mapping) else None
    if not isinstance(operations, Mapping) or "delivery" not in operations:
        raise GoldenPathReceiptError("receipt transport operations are incomplete")
    if any(
        not isinstance(operation, Mapping) or operation.get("ok") is not True
        for operation in operations.values()
    ):
        raise GoldenPathReceiptError("receipt has a failed transport operation")
    return True


def write_request_delivery_receipt(result: Any, path: str | Path) -> dict[str, Any]:
    """Write a verified receipt using stable JSON formatting and return it."""

    receipt = build_request_delivery_receipt(result)
    verify_request_delivery_receipt(receipt)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


__all__ = [
    "GOLDEN_PATH_RECEIPT_SCHEMA",
    "GoldenPathReceiptError",
    "build_request_delivery_receipt",
    "verify_request_delivery_receipt",
    "write_request_delivery_receipt",
]
