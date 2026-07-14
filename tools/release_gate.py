#!/usr/bin/env python3
"""Deterministic release-gate matrix expansion and fail-closed evaluation.

This bounded slice for issue #195 defines the machine-readable matrix contract,
stable case expansion, evidence-bundle schemas, and required-tier promotion
evaluation. It does not execute installs or claim clean-machine proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from itertools import product
from pathlib import Path
from typing import Any, Mapping, Sequence

# The #323 release-manifest contract is kept in a focused module, while these
# re-exports make it available to existing release-gate callers without a
# second import surface.
from tools.release_manifest import (  # noqa: E402
    RELEASE_MANIFEST_SCHEMA,
    RELEASE_REPORT_SCHEMA,
    ROLLBACK_CONTRACT_SCHEMA,
    build_release_manifest,
    build_rollback_contract,
    digest_document,
    evaluate_release_contract,
    validate_release_manifest,
    validate_rollback_contract,
)
from tools.release_gate_scan import (  # noqa: E402
    SCAN_CONTRACT_SCHEMA,
    SCAN_RECEIPT_SCHEMA,
    SURFACE_SCAN_SCHEMA,
    build_release_scan_contract,
    build_release_scan_receipt,
    build_scan_contract,
    build_scan_receipt,
    scan_source_package_runtime,
    scan_surface,
    validate_scan_contract,
    validate_scan_receipt,
    validate_release_scan_contract,
    validate_release_scan_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_SCHEMA = "simplicio.release-matrix/v1"
EXPANDED_SCHEMA = "simplicio.release-matrix-expanded/v1"
EVIDENCE_SCHEMA = "simplicio.release-evidence/v1"
REPORT_SCHEMA = "simplicio.release-gate-report/v1"
ROLLBACK_SCHEMA = "simplicio.release-rollback-evidence/v1"
VERSION = 1
VALID_TIERS = frozenset(("required", "experimental"))
VALID_STATUSES = frozenset(("pass", "fail", "blocked", "skipped"))
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _canonical_json(document: Any) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _digest_document(document: Mapping[str, Any]) -> str:
    return _digest_bytes(json.dumps(document, sort_keys=True).encode("utf-8"))


def _is_sha256_digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256_DIGEST.fullmatch(value) is not None


def build_artifact_descriptor(
    *,
    name: str,
    channel: str,
    kind: str,
    digest: str,
    source_uri: str,
) -> dict[str, str]:
    return {
        "name": name,
        "channel": channel,
        "kind": kind,
        "digest": digest,
        "source_uri": source_uri,
    }


def build_environment_descriptor(
    *,
    runner: str,
    clean_room: bool,
    cache_scope: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_copy = json.loads(json.dumps(manifest, sort_keys=True))
    return {
        "runner": runner,
        "clean_room": clean_room,
        "cache_scope": cache_scope,
        "manifest": manifest_copy,
        "manifest_digest": _digest_document(manifest_copy),
    }


def build_rollback_evidence(
    *,
    from_release: str,
    to_release: str,
    restored_release: str,
    restored_artifact_digest: str,
    state_preserved: bool,
    receipts: Sequence[str],
    restored_identity: Mapping[str, Any] | None = None,
    blocked_reason: str = "",
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema": ROLLBACK_SCHEMA,
        "from_release": from_release,
        "to_release": to_release,
        "restored_release": restored_release,
        "restored_artifact_digest": restored_artifact_digest,
        "state_preserved": bool(state_preserved),
        "receipts": list(receipts),
    }
    if restored_identity is not None:
        evidence["restored_identity"] = json.loads(
            json.dumps(restored_identity, sort_keys=True)
        )
    if blocked_reason:
        evidence["blocked_reason"] = blocked_reason
    return evidence


def build_evidence_record(
    *,
    case_id: str,
    tier: str,
    status: str,
    artifact: Mapping[str, Any],
    environment: Mapping[str, Any],
    receipts: Sequence[str],
    rollback: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "case_id": case_id,
        "tier": tier,
        "status": status,
        "artifact": dict(artifact),
        "environment": json.loads(json.dumps(environment, sort_keys=True)),
        "receipts": list(receipts),
    }
    if rollback is not None:
        record["rollback"] = dict(rollback)
    if notes:
        record["notes"] = list(notes)
    return record


def build_evidence_bundle(
    matrix_document: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": EVIDENCE_SCHEMA,
        "version": VERSION,
        "matrix_digest": _digest_document(matrix_document),
        "records": [dict(record) for record in records],
    }


def _case_id(axis_names: Sequence[str], values: Mapping[str, str]) -> str:
    return "__".join(f"{name}={values[name]}" for name in axis_names)


def _normalise_value(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        if not value:
            raise ValueError("matrix value id must be a non-empty string")
        return {"id": value, "tier": "required"}
    if not isinstance(value, Mapping):
        raise TypeError(f"matrix value must be a string or object, got {type(value)!r}")
    ident = value.get("id")
    tier = value.get("tier", "required")
    if not isinstance(ident, str) or not ident:
        raise ValueError("matrix value id must be a non-empty string")
    if tier not in VALID_TIERS:
        raise ValueError(f"invalid tier: {tier}")
    return {"id": ident, "tier": tier}


def validate_matrix(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["matrix document must be an object"]
    if document.get("schema") != MATRIX_SCHEMA:
        errors.append("schema must be simplicio.release-matrix/v1")
    if document.get("version") != VERSION:
        errors.append("version must be 1")
    axes = document.get("axes")
    if not isinstance(axes, list) or not axes:
        errors.append("axes must be a non-empty list")
        return errors
    axis_names: list[str] = []
    values_by_axis: dict[str, set[str]] = {}
    for index, axis in enumerate(axes):
        prefix = f"axes[{index}]"
        if not isinstance(axis, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        name = axis.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{prefix}.name must be a non-empty string")
            continue
        axis_names.append(name)
        values = axis.get("values")
        if not isinstance(values, list) or not values:
            errors.append(f"{prefix}.values must be a non-empty list")
            continue
        seen: set[str] = set()
        for value_index, raw_value in enumerate(values):
            try:
                value = _normalise_value(raw_value)
            except (TypeError, ValueError) as exc:
                errors.append(f"{prefix}.values[{value_index}] invalid: {exc}")
                continue
            if value["id"] in seen:
                errors.append(f"{prefix}.values ids must be unique: {value['id']}")
            seen.add(value["id"])
        values_by_axis[name] = seen
    if len(axis_names) != len(set(axis_names)):
        errors.append("axis names must be unique")
    excludes = document.get("exclude", [])
    if excludes is not None and not isinstance(excludes, list):
        errors.append("exclude must be a list when present")
    elif isinstance(excludes, list):
        valid_axes = set(values_by_axis)
        for index, rule in enumerate(excludes):
            prefix = f"exclude[{index}]"
            if not isinstance(rule, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            when = rule.get("when")
            if not isinstance(when, Mapping) or not when:
                errors.append(f"{prefix}.when must be a non-empty object")
                continue
            for axis_name, axis_value in when.items():
                if axis_name not in valid_axes:
                    errors.append(f"{prefix}.when references unknown axis: {axis_name}")
                elif axis_value not in values_by_axis[axis_name]:
                    errors.append(
                        f"{prefix}.when references unknown value {axis_name}={axis_value}"
                    )
    return sorted(set(errors))


def expand_matrix(document: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_matrix(document)
    if errors:
        raise ValueError("; ".join(errors))
    axes = list(document["axes"])
    axis_names = [str(axis["name"]) for axis in axes]
    normalised_values = [
        [_normalise_value(value) for value in axis["values"]] for axis in axes
    ]
    excludes = [dict(rule["when"]) for rule in document.get("exclude", [])]
    cases: list[dict[str, Any]] = []
    for choice in product(*normalised_values):
        dimensions = {
            axis_names[index]: value["id"] for index, value in enumerate(choice)
        }
        if any(
            all(dimensions.get(key) == expected for key, expected in rule.items())
            for rule in excludes
        ):
            continue
        experimental_axes = sorted(
            axis_names[index]
            for index, value in enumerate(choice)
            if value["tier"] == "experimental"
        )
        case = {
            "id": _case_id(axis_names, dimensions),
            "tier": "experimental" if experimental_axes else "required",
            "dimensions": dimensions,
            "experimental_axes": experimental_axes,
            "required_evidence": [
                "artifact",
                "environment",
                "receipts",
                *(["rollback"] if dimensions.get("scenario") == "rollback" else []),
            ],
        }
        cases.append(case)
    required = sum(case["tier"] == "required" for case in cases)
    experimental = len(cases) - required
    return {
        "schema": EXPANDED_SCHEMA,
        "version": VERSION,
        "matrix_schema": MATRIX_SCHEMA,
        "matrix_digest": _digest_document(document),
        "axes": json.loads(json.dumps(document["axes"], sort_keys=True)),
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "required": required,
            "experimental": experimental,
        },
    }


def validate_rollback_evidence(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["rollback must be an object"]
    if document.get("schema") != ROLLBACK_SCHEMA:
        errors.append("rollback.schema must be simplicio.release-rollback-evidence/v1")
    for key in (
        "from_release",
        "to_release",
        "restored_release",
        "restored_artifact_digest",
    ):
        if not isinstance(document.get(key), str) or not document[key]:
            errors.append(f"rollback.{key} must be a non-empty string")
    if not isinstance(document.get("state_preserved"), bool):
        errors.append("rollback.state_preserved must be a boolean")
    receipts = document.get("receipts")
    if (
        not isinstance(receipts, list)
        or not receipts
        or not all(isinstance(value, str) and value for value in receipts)
    ):
        errors.append("rollback.receipts must be a non-empty list of strings")
    digest = document.get("restored_artifact_digest", "")
    if not _is_sha256_digest(digest):
        errors.append("rollback.restored_artifact_digest must use sha256")
    identity = document.get("restored_identity")
    if not isinstance(identity, Mapping):
        errors.append("rollback.restored_identity must be an object")
    else:
        if identity.get("compatible") is not True:
            errors.append("rollback.restored_identity.compatible must be true")
        expected_names = {
            "agent": "simplicio-agent",
            "runtime": "simplicio-runtime",
        }
        for component, expected_name in expected_names.items():
            value = identity.get(component)
            prefix = f"rollback.restored_identity.{component}"
            if not isinstance(value, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            if value.get("name") != expected_name:
                errors.append(f"{prefix}.name must be {expected_name}")
            for key in ("version", "digest"):
                if not isinstance(value.get(key), str) or not value[key]:
                    errors.append(f"{prefix}.{key} must be a non-empty string")
            component_digest = value.get("digest")
            if not _is_sha256_digest(component_digest):
                errors.append(f"{prefix}.digest must use sha256")
        agent = identity.get("agent")
        if isinstance(agent, Mapping):
            if agent.get("version") != document.get("restored_release"):
                errors.append(
                    "rollback.restored_identity.agent.version must match restored_release"
                )
            if agent.get("digest") != document.get("restored_artifact_digest"):
                errors.append(
                    "rollback.restored_identity.agent.digest must match "
                    "restored_artifact_digest"
                )
    return sorted(set(errors))


def validate_evidence_bundle(
    document: Mapping[str, Any], matrix_document: Mapping[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["evidence document must be an object"]
    if document.get("schema") != EVIDENCE_SCHEMA:
        errors.append("schema must be simplicio.release-evidence/v1")
    if document.get("version") != VERSION:
        errors.append("version must be 1")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records must be a non-empty list")
        return errors
    expanded = None
    if matrix_document is not None:
        matrix_errors = validate_matrix(matrix_document)
        if matrix_errors:
            errors.extend(f"matrix.{error}" for error in matrix_errors)
        else:
            expanded = expand_matrix(matrix_document)
    valid_cases = {case["id"]: case for case in expanded["cases"]} if expanded else {}
    matrix_digest = document.get("matrix_digest")
    if not _is_sha256_digest(matrix_digest):
        errors.append("matrix_digest must use sha256")
    if matrix_document is not None:
        expected_digest = _digest_document(matrix_document)
        if matrix_digest != expected_digest:
            errors.append("matrix_digest does not match the provided matrix document")
    seen_case_ids: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}.case_id must be a non-empty string")
            continue
        if case_id in seen_case_ids:
            errors.append(f"{prefix}.case_id must be unique: {case_id}")
        seen_case_ids.add(case_id)
        if expanded and case_id not in valid_cases:
            errors.append(f"{prefix}.case_id not present in matrix: {case_id}")
        case = valid_cases.get(case_id)
        tier = record.get("tier")
        if tier not in VALID_TIERS:
            errors.append(f"{prefix}.tier must be one of {sorted(VALID_TIERS)}")
        elif case is not None and tier != case["tier"]:
            errors.append(f"{prefix}.tier does not match matrix tier for {case_id}")
        status = record.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(VALID_STATUSES)}")
        artifact = record.get("artifact")
        if not isinstance(artifact, Mapping):
            errors.append(f"{prefix}.artifact must be an object")
        else:
            digest = artifact.get("digest", "")
            if not _is_sha256_digest(digest):
                errors.append(f"{prefix}.artifact.digest must use sha256")
            for key in ("name", "channel", "kind", "source_uri"):
                if not isinstance(artifact.get(key), str) or not artifact[key]:
                    errors.append(f"{prefix}.artifact.{key} must be a non-empty string")
            if case is not None:
                expected_channel = case["dimensions"].get("channel")
                if expected_channel and artifact.get("channel") != expected_channel:
                    errors.append(
                        f"{prefix}.artifact.channel does not match matrix channel for {case_id}"
                    )
        environment = record.get("environment")
        if not isinstance(environment, Mapping):
            errors.append(f"{prefix}.environment must be an object")
        else:
            for key in ("runner", "cache_scope"):
                if not isinstance(environment.get(key), str) or not environment[key]:
                    errors.append(
                        f"{prefix}.environment.{key} must be a non-empty string"
                    )
            if not _is_sha256_digest(environment.get("manifest_digest")):
                errors.append(f"{prefix}.environment.manifest_digest must use sha256")
            if not isinstance(environment.get("clean_room"), bool):
                errors.append(f"{prefix}.environment.clean_room must be a boolean")
            manifest = environment.get("manifest")
            if not isinstance(manifest, Mapping):
                errors.append(f"{prefix}.environment.manifest must be an object")
            elif environment.get("manifest_digest") != _digest_document(manifest):
                errors.append(f"{prefix}.environment.manifest_digest mismatch")
        receipts = record.get("receipts")
        if (
            not isinstance(receipts, list)
            or not receipts
            or not all(isinstance(value, str) and value for value in receipts)
        ):
            errors.append(f"{prefix}.receipts must be a non-empty list of strings")
        needs_rollback = bool(
            case is not None and case["dimensions"].get("scenario") == "rollback"
        )
        rollback = record.get("rollback")
        if needs_rollback and rollback is None:
            errors.append(f"{prefix}.rollback is required for rollback scenarios")
        if rollback is not None:
            if not isinstance(rollback, Mapping):
                errors.append(f"{prefix}.rollback must be an object")
            else:
                errors.extend(validate_rollback_evidence(rollback))
                if (
                    record.get("status") == "pass"
                    and rollback.get("state_preserved") is not True
                ):
                    errors.append(
                        f"{prefix}.rollback.state_preserved must be true for pass"
                    )
    return sorted(set(errors))


def evaluate_release_gate(
    matrix_document: Mapping[str, Any], evidence_document: Mapping[str, Any]
) -> dict[str, Any]:
    matrix_errors = validate_matrix(matrix_document)
    evidence_errors = validate_evidence_bundle(evidence_document, matrix_document)
    expanded = (
        expand_matrix(matrix_document)
        if not matrix_errors
        else {
            "matrix_digest": _digest_document(matrix_document)
            if isinstance(matrix_document, Mapping)
            else "",
            "cases": [],
        }
    )
    evidence_records = (
        evidence_document.get("records", [])
        if isinstance(evidence_document, Mapping)
        else []
    )
    if not isinstance(evidence_records, list):
        evidence_records = []
    records = {
        str(record["case_id"]): dict(record)
        for record in evidence_records
        if isinstance(record, Mapping) and "case_id" in record
    }
    required: list[dict[str, Any]] = []
    experimental: list[dict[str, Any]] = []
    for case in expanded["cases"]:
        record = records.get(case["id"])
        status = "missing" if record is None else str(record.get("status"))
        entry = {
            "case_id": case["id"],
            "tier": case["tier"],
            "status": status,
            "ok": status == "pass",
        }
        if case["tier"] == "required":
            required.append(entry)
        else:
            experimental.append(entry)
    required_missing = [
        entry["case_id"] for entry in required if entry["status"] == "missing"
    ]
    required_failed = [
        entry["case_id"]
        for entry in required
        if entry["status"] not in {"pass", "missing"}
    ]
    required_ok = (
        not matrix_errors
        and not evidence_errors
        and not required_missing
        and not required_failed
    )
    experimental_passed = sum(entry["status"] == "pass" for entry in experimental)
    return {
        "schema": REPORT_SCHEMA,
        "version": VERSION,
        "matrix_digest": expanded["matrix_digest"],
        "validation": {
            "ok": not matrix_errors and not evidence_errors,
            "matrix_errors": matrix_errors,
            "evidence_errors": evidence_errors,
        },
        "required": {
            "total": len(required),
            "passed": sum(entry["status"] == "pass" for entry in required),
            "missing": required_missing,
            "failed": required_failed,
            "ok": required_ok,
        },
        "experimental": {
            "total": len(experimental),
            "passed": experimental_passed,
            "observed": len(experimental)
            - sum(entry["status"] == "missing" for entry in experimental),
        },
        "cases": required + experimental,
        "summary": {
            "ok": required_ok,
            "stable_promotion": "allow" if required_ok else "block",
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(document: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_canonical_json(document), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    expand_parser = subparsers.add_parser("expand", help="expand a release matrix")
    expand_parser.add_argument("matrix", help="path to release-matrix/v1 JSON")
    expand_parser.add_argument(
        "--write", metavar="PATH", help="write expanded JSON to PATH"
    )

    validate_matrix_parser = subparsers.add_parser(
        "validate-matrix", help="validate a release-matrix/v1 JSON"
    )
    validate_matrix_parser.add_argument("matrix", help="path to release-matrix/v1 JSON")

    validate_evidence_parser = subparsers.add_parser(
        "validate-evidence", help="validate a release-evidence/v1 JSON"
    )
    validate_evidence_parser.add_argument(
        "matrix", help="path to release-matrix/v1 JSON"
    )
    validate_evidence_parser.add_argument(
        "evidence", help="path to release-evidence/v1 JSON"
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate required-tier promotion against evidence"
    )
    evaluate_parser.add_argument("matrix", help="path to release-matrix/v1 JSON")
    evaluate_parser.add_argument("evidence", help="path to release-evidence/v1 JSON")
    evaluate_parser.add_argument(
        "--write", metavar="PATH", help="write report JSON to PATH"
    )

    args = parser.parse_args(argv)

    if args.command == "expand":
        matrix_document = _read_json(Path(args.matrix))
        expanded = expand_matrix(matrix_document)
        if args.write:
            _write_json(expanded, Path(args.write))
        else:
            print(_canonical_json(expanded), end="")
        return 0

    if args.command == "validate-matrix":
        matrix_document = _read_json(Path(args.matrix))
        errors = validate_matrix(matrix_document)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("valid")
        return 0

    if args.command == "validate-evidence":
        matrix_document = _read_json(Path(args.matrix))
        evidence_document = _read_json(Path(args.evidence))
        errors = validate_evidence_bundle(evidence_document, matrix_document)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("valid")
        return 0

    if args.command == "evaluate":
        matrix_document = _read_json(Path(args.matrix))
        evidence_document = _read_json(Path(args.evidence))
        report = evaluate_release_gate(matrix_document, evidence_document)
        if args.write:
            _write_json(report, Path(args.write))
        else:
            print(_canonical_json(report), end="")
        return 0 if report["summary"]["ok"] else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
