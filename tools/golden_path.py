"""Build and verify a bounded request-to-delivery receipt.

The existing ``agent.golden_path`` harness proves the fixture operation path.
This module owns the smaller audit boundary: it turns one completed harness
result into a portable receipt, verifies every required receipt artifact, and
provides a fixture-scoped executable gate. It refuses claims that the fixture
run was a clean-machine end-to-end test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


GOLDEN_PATH_RECEIPT_SCHEMA = "simplicio-agent/issue-211-golden-path-receipt/v1"
_REQUIRED_RECEIPT_STEPS = (
    "orient",
    "plan",
    "lease",
    "mutation",
    "validation",
    "requery",
    "evidence",
    "delivery",
)
_EVIDENCE_RECEIPT_STEPS = ("validation", "requery", "evidence")


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


def _verified_receipt_artifacts(
    result: Any, evidence_refs: list[str]
) -> dict[str, dict[str, str]]:
    refs = _field(result, "receipt_refs", {}) or {}
    files = _field(result, "receipt_files", {}) or {}
    if not isinstance(refs, Mapping) or not isinstance(files, Mapping):
        raise GoldenPathReceiptError("result receipt artifacts must be mappings")

    artifacts: dict[str, dict[str, str]] = {}
    for step in _REQUIRED_RECEIPT_STEPS:
        ref = refs.get(step)
        if not isinstance(ref, str) or not ref.startswith("receipt://"):
            raise GoldenPathReceiptError(f"{step} receipt reference is missing")
        digest = ref.removeprefix("receipt://")
        path_value = files.get(step)
        if not isinstance(path_value, str) or not path_value:
            raise GoldenPathReceiptError(f"{step} receipt artifact path is missing")
        path = Path(path_value)
        if not path.is_file():
            raise GoldenPathReceiptError(f"{step} receipt artifact is missing: {path}")
        try:
            persisted = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoldenPathReceiptError(
                f"{step} receipt artifact is unreadable: {path}"
            ) from exc
        meta = persisted.get("meta") if isinstance(persisted, Mapping) else None
        if (
            not isinstance(persisted, Mapping)
            or path.stem != digest
            or persisted.get("sha") != digest
            or persisted.get("status") != "ok"
            or not isinstance(meta, Mapping)
            or meta.get("step") != step
        ):
            raise GoldenPathReceiptError(
                f"{step} receipt artifact does not match its reference"
            )
        if step in _EVIDENCE_RECEIPT_STEPS and ref not in evidence_refs:
            raise GoldenPathReceiptError(
                f"{step} receipt is not linked from envelope evidence_refs"
            )
        artifacts[step] = {"receipt_ref": ref, "status": "ok"}
    return artifacts


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
    receipt_artifacts = _verified_receipt_artifacts(result, evidence_refs)

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
        "evidence": {"artifacts": receipt_artifacts},
        "mutation": {
            "write_set": list(_field(requery, "write_set", ()) or ()),
            "final_state": dict(_field(result, "final_state", {}) or {}),
            "requery_matches_expected": True,
        },
        "transport": {"operations": operations},
        "delivery": {
            "accepted": True,
            "target": target,
            "receipt_ref": receipt_artifacts["delivery"]["receipt_ref"],
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
    evidence = receipt.get("evidence")
    artifacts = evidence.get("artifacts") if isinstance(evidence, Mapping) else None
    if not isinstance(artifacts, Mapping):
        raise GoldenPathReceiptError("receipt has no evidence artifacts")
    for step in _REQUIRED_RECEIPT_STEPS:
        artifact = artifacts.get(step)
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("status") != "ok"
            or not isinstance(artifact.get("receipt_ref"), str)
            or not artifact["receipt_ref"].startswith("receipt://")
        ):
            raise GoldenPathReceiptError(
                f"receipt evidence artifact is incomplete: {step}"
            )
    for step in _EVIDENCE_RECEIPT_STEPS:
        if artifacts[step]["receipt_ref"] not in lifecycle["evidence_refs"]:
            raise GoldenPathReceiptError(
                f"receipt evidence_refs do not link artifact: {step}"
            )
    mutation = receipt.get("mutation")
    if (
        not isinstance(mutation, Mapping)
        or mutation.get("requery_matches_expected") is not True
    ):
        raise GoldenPathReceiptError("receipt lacks a passing independent requery")
    delivery = receipt.get("delivery")
    if not isinstance(delivery, Mapping) or delivery.get("accepted") is not True:
        raise GoldenPathReceiptError("delivery was not accepted")
    if delivery.get("receipt_ref") != artifacts["delivery"]["receipt_ref"]:
        raise GoldenPathReceiptError(
            "delivery receipt reference does not match evidence"
        )
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


def execute_fixture_golden_path(
    fixture_root: str | Path,
    output: str | Path,
    *,
    cli_bin: str | None = None,
    allow_fixture_mcp_fallback: bool = False,
) -> dict[str, Any]:
    """Execute the bounded fixture path and persist its verified receipt."""

    from agent.golden_path import (
        GoldenPathHarness,
        GoldenPathScenario,
        build_fixture_mcp_call,
    )

    root = Path(fixture_root).resolve()
    scenario_path = root / "scenario.json"
    scenario = GoldenPathScenario.from_path(root)
    mcp_call = build_fixture_mcp_call(scenario) if allow_fixture_mcp_fallback else None
    previous_scenario = os.environ.get("GOLDEN_PATH_SCENARIO")
    os.environ["GOLDEN_PATH_SCENARIO"] = str(scenario_path)
    try:
        result = GoldenPathHarness.from_fixture(
            root,
            cli_bin=cli_bin,
            mcp_call=mcp_call,
        ).run()
        receipt = write_request_delivery_receipt(result, output)
    finally:
        if previous_scenario is None:
            os.environ.pop("GOLDEN_PATH_SCENARIO", None)
        else:
            os.environ["GOLDEN_PATH_SCENARIO"] = previous_scenario
    return {
        "status": "MEASURED",
        "proof_scope": receipt["proof"]["scope"],
        "lifecycle_state": receipt["lifecycle"]["state"],
        "receipt_sha256": receipt["receipt_sha256"],
        "output": str(Path(output).resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    """Run the fixture golden path as a fail-closed executable gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="Mutable fixture root")
    parser.add_argument("--output", required=True, help="Verified receipt output path")
    parser.add_argument("--cli-bin", help="Simplicio-compatible CLI executable")
    parser.add_argument(
        "--allow-fixture-mcp-fallback",
        action="store_true",
        help="Allow the fixture MCP adapter only when the CLI is unavailable",
    )
    args = parser.parse_args(argv)
    try:
        report = execute_fixture_golden_path(
            args.fixture,
            args.output,
            cli_bin=args.cli_bin,
            allow_fixture_mcp_fallback=args.allow_fixture_mcp_fallback,
        )
    except (
        GoldenPathReceiptError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print(
            json.dumps({"status": "UNVERIFIED", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


__all__ = [
    "GOLDEN_PATH_RECEIPT_SCHEMA",
    "GoldenPathReceiptError",
    "build_request_delivery_receipt",
    "execute_fixture_golden_path",
    "main",
    "verify_request_delivery_receipt",
    "write_request_delivery_receipt",
]


if __name__ == "__main__":
    raise SystemExit(main())
