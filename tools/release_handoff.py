"""Produce a deterministic, fail-closed release handoff audit receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from agent.release_handoff_contract import (
    ArtifactEvidence,
    ChecksumEvidence,
    DefaultOffIntegrationEvidence,
    EvidenceStatus,
    LifecycleEvidence,
    RuntimeSurfaceEvidence,
    audit_release_handoff,
)


def _status(value: Any) -> EvidenceStatus:
    try:
        return EvidenceStatus(str(value or "missing"))
    except ValueError as exc:
        raise ValueError(f"invalid evidence status: {value!r}") from exc


def _lifecycle(payload: Mapping[str, Any], name: str) -> LifecycleEvidence:
    item = payload.get(name, {})
    if item is None:
        item = {}
    if not isinstance(item, Mapping):
        raise ValueError(f"{name} evidence must be an object")
    return LifecycleEvidence(
        receipt=item.get("receipt"),
        status=_status(item.get("status")),
        notes=item.get("notes"),
    )


def audit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a JSON evidence envelope into the canonical handoff receipt."""

    evidence = payload.get("evidence", payload)
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must be an object")
    def items(name: str) -> tuple[Mapping[str, Any], ...]:
        raw = evidence.get(name, [])
        if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
            raise ValueError(f"{name} evidence must be a list of objects")
        return tuple(raw)

    artifact_items = items("artifacts")
    checksum_items = items("checksums")
    runtime_items = items("runtime_surfaces")
    default_off_items = items("default_off_integrations")
    artifacts = tuple(
        ArtifactEvidence(str(item.get("path", "")), item.get("receipt"))
        for item in artifact_items
    )
    checksums = tuple(
        ChecksumEvidence(str(item.get("artifact", "")), item.get("sha256"), item.get("receipt"))
        for item in checksum_items
    )
    runtime_surfaces = tuple(
        RuntimeSurfaceEvidence(str(item.get("name", "")), item.get("receipt"), _status(item.get("status")))
        for item in runtime_items
    )
    default_off = tuple(
        DefaultOffIntegrationEvidence(
            str(item.get("name", "")), bool(item.get("enabled", False)),
            item.get("receipt"), _status(item.get("status")),
        )
        for item in default_off_items
    )
    audit = audit_release_handoff(
        artifacts=artifacts,
        checksums=checksums,
        install=_lifecycle(evidence, "install"),
        update=_lifecycle(evidence, "update"),
        rollback=_lifecycle(evidence, "rollback"),
        uninstall=_lifecycle(evidence, "uninstall"),
        runtime_surfaces=runtime_surfaces,
        default_off_integrations=default_off,
    )
    return audit.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="evidence JSON envelope")
    parser.add_argument("--output", required=True, type=Path, help="audit receipt JSON")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        receipt = audit_payload(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"release-handoff: invalid input: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
