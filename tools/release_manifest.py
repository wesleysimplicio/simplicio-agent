"""Content-addressed release and rollback contracts for local release gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

RELEASE_MANIFEST_SCHEMA = "simplicio.release-manifest/v1"
ROLLBACK_CONTRACT_SCHEMA = "simplicio.release-rollback/v1"
RELEASE_REPORT_SCHEMA = "simplicio.release-contract-report/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def digest_document(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def build_release_manifest(
    *,
    version: str,
    source_commit: str,
    artifact: Mapping[str, Any],
    runtime: Mapping[str, Any],
    files: Sequence[Mapping[str, str]] = (),
    identity: str = "simplicio-agent",
) -> dict[str, Any]:
    manifest = {
        "schema": RELEASE_MANIFEST_SCHEMA,
        "version": version,
        "source_commit": source_commit,
        "identity": identity,
        "artifact": dict(artifact),
        "runtime": dict(runtime),
        "files": [dict(item) for item in files],
    }
    manifest["manifest_digest"] = digest_document(manifest)
    return manifest


def build_rollback_contract(
    *,
    from_manifest_digest: str,
    to_manifest_digest: str,
    restored_manifest_digest: str,
    receipts: Sequence[str],
    state_preserved: bool,
    restored_identity: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": ROLLBACK_CONTRACT_SCHEMA,
        "from_manifest_digest": from_manifest_digest,
        "to_manifest_digest": to_manifest_digest,
        "restored_manifest_digest": restored_manifest_digest,
        "receipts": list(receipts),
        "state_preserved": bool(state_preserved),
        "restored_identity": json.loads(json.dumps(restored_identity, sort_keys=True)),
    }


def _digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def validate_release_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest must be an object"]
    if manifest.get("schema") != RELEASE_MANIFEST_SCHEMA:
        errors.append(f"schema must be {RELEASE_MANIFEST_SCHEMA}")
    for key in ("version", "source_commit", "identity"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            errors.append(f"{key} must be a non-empty string")
    if manifest.get("identity") != "simplicio-agent":
        errors.append("identity must be simplicio-agent")
    artifact = manifest.get("artifact")
    if not isinstance(artifact, Mapping):
        errors.append("artifact must be an object")
    else:
        for key in ("name", "kind", "channel", "digest"):
            if not isinstance(artifact.get(key), str) or not artifact[key]:
                errors.append(f"artifact.{key} must be a non-empty string")
        if not _digest(artifact.get("digest")):
            errors.append("artifact.digest must use sha256")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping):
        errors.append("runtime must be an object")
    else:
        if runtime.get("name") != "simplicio-runtime":
            errors.append("runtime.name must be simplicio-runtime")
        for key in ("version", "digest"):
            if not isinstance(runtime.get(key), str) or not runtime[key]:
                errors.append(f"runtime.{key} must be a non-empty string")
        if not _digest(runtime.get("digest")):
            errors.append("runtime.digest must use sha256")
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("files must be a list")
    else:
        seen: set[str] = set()
        for index, item in enumerate(files):
            if (
                not isinstance(item, Mapping)
                or not item.get("path")
                or not _digest(item.get("digest"))
            ):
                errors.append(f"files[{index}] requires path and sha256 digest")
                continue
            if item["path"] in seen:
                errors.append(f"files[{index}].path must be unique")
            seen.add(str(item["path"]))
    expected = dict(manifest)
    supplied = expected.pop("manifest_digest", None)
    if not _digest(supplied):
        errors.append("manifest_digest must use sha256")
    elif supplied != digest_document(expected):
        errors.append("manifest_digest does not match manifest contents")
    return sorted(set(errors))


def validate_rollback_contract(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != ROLLBACK_CONTRACT_SCHEMA:
        errors.append(f"schema must be {ROLLBACK_CONTRACT_SCHEMA}")
    for key in (
        "from_manifest_digest",
        "to_manifest_digest",
        "restored_manifest_digest",
    ):
        if not _digest(contract.get(key)):
            errors.append(f"{key} must use sha256")
    if not contract.get("state_preserved") is True:
        errors.append("state_preserved must be true")
    receipts = contract.get("receipts")
    if (
        not isinstance(receipts, list)
        or not receipts
        or not all(isinstance(item, str) and item for item in receipts)
    ):
        errors.append("receipts must be a non-empty list of strings")
    identity = contract.get("restored_identity")
    if (
        not isinstance(identity, Mapping)
        or identity.get("name") != "simplicio-agent"
        or not _digest(identity.get("manifest_digest"))
    ):
        errors.append("restored_identity must pin the simplicio-agent manifest digest")
    elif identity.get("manifest_digest") != contract.get("restored_manifest_digest"):
        errors.append(
            "restored_identity.manifest_digest must match restored_manifest_digest"
        )
    return sorted(set(errors))


def evaluate_release_contract(
    manifest: Mapping[str, Any], rollback: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    manifest_errors = validate_release_manifest(manifest)
    rollback_errors = (
        validate_rollback_contract(rollback) if rollback is not None else []
    )
    return {
        "schema": RELEASE_REPORT_SCHEMA,
        "ok": not manifest_errors and not rollback_errors,
        "manifest": {"ok": not manifest_errors, "errors": manifest_errors},
        "rollback": {
            "ok": rollback is None or not rollback_errors,
            "errors": rollback_errors,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rollback = (
        json.loads(args.rollback.read_text(encoding="utf-8")) if args.rollback else None
    )
    result = evaluate_release_contract(manifest, rollback)
    print(
        json.dumps(result, indent=2, sort_keys=True)
        if args.json
        else ("release-contract: PASS" if result["ok"] else "release-contract: BLOCK")
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
