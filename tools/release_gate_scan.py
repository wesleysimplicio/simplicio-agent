"""Read-only release-gate scan contracts and digest-pinned receipts.

The release gate owns the *shape* of clean-install, upgrade, and rollback
evidence.  This module deliberately does not invoke an installer, activate a
release, or publish an artifact.  It records deterministic observations from
already-produced inputs and makes the boundary explicit in the receipt.

The source, package, and runtime surfaces are supplied by a caller so this
layer can be used by a local fixture or by a future CI operator without
coupling the release gate to a particular packaging tool.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Mapping, Sequence

# ``python tools/release_gate_scan.py`` puts ``tools/`` on sys.path rather than
# the repository root.  Keep the documented script invocation self-contained.
if __package__ in {None, ""}:  # pragma: no cover - exercised by the CLI
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.identity_scan import IdentityFinding, scan_text, validate_manifest
from tools.release_manifest import (
    digest_document,
    validate_release_manifest,
)

SCAN_CONTRACT_SCHEMA = "simplicio.release-scan-contract/v1"
SURFACE_SCAN_SCHEMA = "simplicio.release-surface-scan/v1"
SCAN_RECEIPT_SCHEMA = "simplicio.release-scan-receipt/v1"
VERSION = 1
SURFACES = ("source", "package", "runtime")
SCENARIOS = ("clean-install", "upgrade", "rollback")
_STATUS = frozenset(("pass", "fail", "blocked", "not_attempted"))
_DIGEST_PREFIX = "sha256:"
_HEX = frozenset("0123456789abcdef")


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_DIGEST_PREFIX)
        and len(value) == len(_DIGEST_PREFIX) + 64
        and all(char in _HEX for char in value[len(_DIGEST_PREFIX) :])
    )


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _sha256_bytes(payload: bytes) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def _finding_dict(finding: IdentityFinding) -> dict[str, Any]:
    return finding.to_dict()


def _surface_members(root: Path, paths: Sequence[str]) -> list[tuple[str, bytes]]:
    """Return deterministic, root-relative file contents for a surface.

    A zip package is read without extracting it.  This keeps scans bounded and
    prevents a release-gate check from writing into the checkout or a temp
    environment.  Directory traversal is sorted and symlinks are not followed.
    """

    members: list[tuple[str, bytes]] = []
    for raw_path in paths:
        relative = Path(raw_path)
        candidate = root / relative
        if candidate.is_symlink():
            raise ValueError(f"surface path must not be a symlink: {raw_path}")
        target = candidate.resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"surface path escapes root: {raw_path}") from exc
        if target.is_dir():
            for child in sorted(target.rglob("*")):
                if child.is_file() and not child.is_symlink():
                    name = child.relative_to(root).as_posix()
                    members.append((name, child.read_bytes()))
            continue
        if not target.is_file():
            raise FileNotFoundError(raw_path)
        if target.suffix.lower() in {".whl", ".zip"}:
            with zipfile.ZipFile(target) as archive:
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    members.append((
                        f"{relative.as_posix()}!{name}",
                        archive.read(name),
                    ))
        else:
            members.append((relative.as_posix(), target.read_bytes()))
    return members


def scan_surface(
    root: str | Path,
    *,
    kind: str,
    paths: Sequence[str],
    identity_manifest: Mapping[str, Any] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Scan one source/package/runtime surface without changing the filesystem."""

    if kind not in SURFACES:
        raise ValueError(f"kind must be one of {SURFACES}")
    if not paths:
        raise ValueError("paths must be non-empty")
    root_path = Path(root).resolve()
    members = _surface_members(root_path, paths)
    files: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    manifest = identity_manifest or {
        "schema": "simplicio.identity-legacy-manifest/v1",
        "version": 1,
        "entries": [],
    }
    manifest_errors = validate_manifest(manifest, today=today)
    for name, payload in members:
        files.append({
            "path": name,
            "size": len(payload),
            "digest": _sha256_bytes(payload),
        })
        if manifest_errors:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(
            _finding_dict(finding)
            for finding in scan_text(name, text, manifest, today=today)
        )
    blocking = [
        finding
        for finding in findings
        if finding["classification"] in {"legacy", "expired"}
    ]
    payload = {
        "schema": SURFACE_SCAN_SCHEMA,
        "version": VERSION,
        "kind": kind,
        "files": files,
        "identity_manifest_digest": digest_document(manifest),
        "identity_manifest_errors": manifest_errors,
        "findings": findings,
        "blocking_count": len(blocking),
        "ok": not manifest_errors and not blocking,
    }
    payload["scan_digest"] = digest_document(payload)
    return payload


def scan_source_package_runtime(
    root: str | Path,
    *,
    paths: Mapping[str, Sequence[str]],
    identity_manifest: Mapping[str, Any] | None = None,
    today: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Scan exactly the three release surfaces in a stable order."""

    missing = [kind for kind in SURFACES if kind not in paths]
    if missing:
        raise ValueError(f"paths missing required surfaces: {', '.join(missing)}")
    return {
        kind: scan_surface(
            root,
            kind=kind,
            paths=paths[kind],
            identity_manifest=identity_manifest,
            today=today,
        )
        for kind in SURFACES
    }


def build_scan_contract(
    *,
    scenario: str,
    manifest: Mapping[str, Any],
    surfaces: Mapping[str, Sequence[str]],
    receipts: Sequence[str],
) -> dict[str, Any]:
    """Build a bounded plan for one release scenario.

    The contract is a plan, not evidence.  ``receipts`` are references to
    evidence producers and may be empty only for a not-yet-attempted plan;
    validation of a completed receipt requires them to be present.
    """

    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    missing = [kind for kind in SURFACES if kind not in surfaces]
    if missing:
        raise ValueError(f"surfaces missing required kinds: {', '.join(missing)}")
    return {
        "schema": SCAN_CONTRACT_SCHEMA,
        "version": VERSION,
        "scenario": scenario,
        "operation": {"name": scenario, "bounded": True},
        "manifest_digest": manifest.get("manifest_digest"),
        "surfaces": {
            kind: {"paths": list(surfaces[kind]), "required": True} for kind in SURFACES
        },
        "receipts": list(receipts),
        "proof": {
            "mutates_release": False,
            "publishes_artifact": False,
            "external_services": False,
            "clean_machine_e2e": "not_claimed",
        },
    }


def validate_scan_contract(
    contract: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate a scan plan and reject execution/publishing claims."""

    errors: list[str] = []
    if not isinstance(contract, Mapping):
        return ["contract must be an object"]
    if contract.get("schema") != SCAN_CONTRACT_SCHEMA:
        errors.append(f"schema must be {SCAN_CONTRACT_SCHEMA}")
    if contract.get("version") != VERSION:
        errors.append("version must be 1")
    if contract.get("scenario") not in SCENARIOS:
        errors.append("scenario must be clean-install, upgrade, or rollback")
    operation = contract.get("operation")
    if not isinstance(operation, Mapping) or operation.get("bounded") is not True:
        errors.append("operation.bounded must be true")
    proof = contract.get("proof")
    if not isinstance(proof, Mapping):
        errors.append("proof must be an object")
    else:
        if proof.get("mutates_release") is not False:
            errors.append("proof.mutates_release must be false")
        if proof.get("publishes_artifact") is not False:
            errors.append("proof.publishes_artifact must be false")
        if proof.get("external_services") is not False:
            errors.append("proof.external_services must be false")
        if proof.get("clean_machine_e2e") != "not_claimed":
            errors.append("proof.clean_machine_e2e must be not_claimed")
    digest = contract.get("manifest_digest")
    if not _is_digest(digest):
        errors.append("manifest_digest must use sha256")
    if manifest is not None:
        errors.extend(
            f"manifest.{error}" for error in validate_release_manifest(manifest)
        )
        if digest != manifest.get("manifest_digest"):
            errors.append("manifest_digest does not match manifest")
    surfaces = contract.get("surfaces")
    if not isinstance(surfaces, Mapping):
        errors.append("surfaces must be an object")
    else:
        for kind in SURFACES:
            descriptor = surfaces.get(kind)
            if not isinstance(descriptor, Mapping):
                errors.append(f"surfaces.{kind} must be an object")
                continue
            paths = descriptor.get("paths")
            if (
                not isinstance(paths, list)
                or not paths
                or not all(isinstance(path, str) and path for path in paths)
            ):
                errors.append(
                    f"surfaces.{kind}.paths must be a non-empty list of strings"
                )
            if descriptor.get("required") is not True:
                errors.append(f"surfaces.{kind}.required must be true")
    receipts = contract.get("receipts")
    if receipts is not None and (
        not isinstance(receipts, list)
        or not all(isinstance(receipt, str) and receipt for receipt in receipts)
    ):
        errors.append("receipts must be a list of non-empty strings")
    return sorted(set(errors))


def build_scan_receipt(
    contract: Mapping[str, Any],
    *,
    scans: Mapping[str, Mapping[str, Any]],
    status: str,
    receipts: Sequence[str],
) -> dict[str, Any]:
    """Build a digest-pinned observation receipt for a scan contract."""

    contract_errors = validate_scan_contract(contract)
    if contract_errors:
        raise ValueError("invalid scan contract: " + "; ".join(contract_errors))
    if status not in _STATUS:
        raise ValueError(f"status must be one of {sorted(_STATUS)}")
    if not receipts:
        raise ValueError("receipts must be non-empty")
    missing = [kind for kind in SURFACES if kind not in scans]
    if missing:
        raise ValueError(f"scans missing required surfaces: {', '.join(missing)}")
    scan_errors: list[str] = []
    for kind in SURFACES:
        scan = scans[kind]
        if scan.get("schema") != SURFACE_SCAN_SCHEMA:
            scan_errors.append(f"scans.{kind}.schema is invalid")
        if scan.get("kind") != kind:
            scan_errors.append(f"scans.{kind}.kind does not match surface")
        if not _is_digest(scan.get("scan_digest")):
            scan_errors.append(f"scans.{kind}.scan_digest must use sha256")
    if scan_errors:
        raise ValueError("invalid surface scans: " + "; ".join(scan_errors))
    payload: dict[str, Any] = {
        "schema": SCAN_RECEIPT_SCHEMA,
        "version": VERSION,
        "contract_digest": digest_document(contract),
        "scenario": contract["scenario"],
        "status": status,
        "manifest_digest": contract["manifest_digest"],
        "surfaces": {kind: _copy(scans[kind]) for kind in SURFACES},
        "receipts": list(receipts),
        "proof": _copy(contract["proof"]),
    }
    payload["receipt_digest"] = digest_document(payload)
    return payload


def validate_scan_receipt(
    receipt: Mapping[str, Any],
    *,
    contract: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate receipt integrity, contract binding, and scan digests."""

    errors: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    if receipt.get("schema") != SCAN_RECEIPT_SCHEMA:
        errors.append(f"schema must be {SCAN_RECEIPT_SCHEMA}")
    if receipt.get("version") != VERSION:
        errors.append("version must be 1")
    if receipt.get("scenario") not in SCENARIOS:
        errors.append("scenario must be clean-install, upgrade, or rollback")
    if receipt.get("status") not in _STATUS - {"not_attempted"}:
        errors.append("status must be pass, fail, or blocked")
    if not _is_digest(receipt.get("contract_digest")):
        errors.append("contract_digest must use sha256")
    if not _is_digest(receipt.get("manifest_digest")):
        errors.append("manifest_digest must use sha256")
    receipts = receipt.get("receipts")
    if (
        not isinstance(receipts, list)
        or not receipts
        or not all(isinstance(item, str) and item for item in receipts)
    ):
        errors.append("receipts must be a non-empty list of strings")
    proof = receipt.get("proof")
    if not isinstance(proof, Mapping):
        errors.append("proof must be an object")
    else:
        if proof.get("mutates_release") is not False:
            errors.append("proof.mutates_release must be false")
        if proof.get("publishes_artifact") is not False:
            errors.append("proof.publishes_artifact must be false")
        if proof.get("clean_machine_e2e") != "not_claimed":
            errors.append("proof.clean_machine_e2e must be not_claimed")
    surfaces = receipt.get("surfaces")
    if not isinstance(surfaces, Mapping):
        errors.append("surfaces must be an object")
    else:
        for kind in SURFACES:
            scan = surfaces.get(kind)
            if not isinstance(scan, Mapping):
                errors.append(f"surfaces.{kind} must be an object")
                continue
            if scan.get("schema") != SURFACE_SCAN_SCHEMA:
                errors.append(f"surfaces.{kind}.schema is invalid")
            if scan.get("kind") != kind:
                errors.append(f"surfaces.{kind}.kind does not match surface")
            digest = scan.get("scan_digest")
            if not _is_digest(digest):
                errors.append(f"surfaces.{kind}.scan_digest must use sha256")
            else:
                unsigned = dict(scan)
                unsigned.pop("scan_digest", None)
                if digest != digest_document(unsigned):
                    errors.append(
                        f"surfaces.{kind}.scan_digest does not match contents"
                    )
    observed_digest = receipt.get("receipt_digest")
    if not _is_digest(observed_digest):
        errors.append("receipt_digest must use sha256")
    else:
        unsigned_receipt = dict(receipt)
        unsigned_receipt.pop("receipt_digest", None)
        if observed_digest != digest_document(unsigned_receipt):
            errors.append("receipt_digest does not match canonical payload")
    if contract is not None:
        errors.extend(f"contract.{error}" for error in validate_scan_contract(contract))
        if receipt.get("contract_digest") != digest_document(contract):
            errors.append("contract_digest does not match contract")
        if receipt.get("scenario") != contract.get("scenario"):
            errors.append("scenario does not match contract")
        if receipt.get("manifest_digest") != contract.get("manifest_digest"):
            errors.append("manifest_digest does not match contract")
        if receipt.get("proof") != contract.get("proof"):
            errors.append("proof does not match contract")
    return sorted(set(errors))


__all__ = [
    "SCAN_CONTRACT_SCHEMA",
    "SCAN_RECEIPT_SCHEMA",
    "SCENARIOS",
    "SURFACE_SCAN_SCHEMA",
    "SURFACES",
    "build_scan_contract",
    "build_scan_receipt",
    "build_release_scan_contract",
    "build_release_scan_receipt",
    "main",
    "scan_source_package_runtime",
    "scan_surface",
    "validate_scan_contract",
    "validate_scan_receipt",
    "validate_release_scan_contract",
    "validate_release_scan_receipt",
]

# Descriptive aliases keep this layer consistent with ``release_manifest``
# while retaining the shorter names used by the matrix gate.
build_release_scan_contract = build_scan_contract
build_release_scan_receipt = build_scan_receipt
validate_release_scan_contract = validate_scan_contract
validate_release_scan_receipt = validate_scan_receipt


def main(argv: Sequence[str] | None = None) -> int:
    """Validate committed contract/receipt JSON without running a release."""

    parser = ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    contract_parser = subparsers.add_parser("validate-contract")
    contract_parser.add_argument("contract", type=Path)
    contract_parser.add_argument("--manifest", type=Path)
    receipt_parser = subparsers.add_parser("validate-receipt")
    receipt_parser.add_argument("receipt", type=Path)
    receipt_parser.add_argument("--contract", type=Path)
    args = parser.parse_args(argv)

    if args.command == "validate-contract":
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        manifest = (
            json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.manifest
            else None
        )
        errors = validate_scan_contract(contract, manifest=manifest)
    else:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        contract = (
            json.loads(args.contract.read_text(encoding="utf-8"))
            if args.contract
            else None
        )
        errors = validate_scan_receipt(receipt, contract=contract)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
