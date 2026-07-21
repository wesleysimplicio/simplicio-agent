#!/usr/bin/env python3
"""Build and validate the machine-readable rename inventory (issue #187)."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from tools.rename_guard.artifact_scan import scan_archive
from tools.rename_guard.scanner import (
    DEFAULT_ALLOWLIST,
    DEFAULT_BASELINE,
    DEFAULT_CONFIG,
    Occurrence,
    allowlist_match,
    load_json,
    scan,
    top_level_surface,
)

DEFAULT_CLASSIFICATION = Path(__file__).with_name("baseline-classification.json")

CLASS_MAP = {
    "credit": "upstream-attribution",
    "upstream": "upstream-attribution",
    "KEEP_UPSTREAM_REFERENCE": "upstream-attribution",
    "fixture": "historical-fixture",
    "historical-fixture": "historical-fixture",
    "alias": "compatibility-temporary",
    "compatibility-temporary": "compatibility-temporary",
    "KEEP_INTERNAL": "private-internal-reviewed",
    "private-internal-reviewed": "private-internal-reviewed",
    "public-must-migrate": "public-must-migrate",
    "GENERATED_REBUILD": "generated-rebuild",
    "MIGRATE_STATE": "migrate-state",
    "error": "error",
    "new": "error",
}

DEFAULT_ISSUE_BY_CLASS = {
    "credit": "#193",
    "upstream": "#193",
    "KEEP_UPSTREAM_REFERENCE": "#193",
    "historical-fixture": "#193",
    "KEEP_INTERNAL": "#190",
    "private-internal-reviewed": "#190",
    "compatibility-temporary": "#190",
    "MIGRATE_STATE": "#117",
    "public-must-migrate": "#118",
    "GENERATED_REBUILD": "#188",
}


def _bare_path(path: str) -> tuple[str, str]:
    for prefix, artifact in (("wheel:", "wheel"), ("sdist:", "sdist")):
        if path.startswith(prefix):
            return path[len(prefix):], artifact
    return path, "source-tree"


def _classification_data(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {entry["path"]: entry for entry in payload.get("files", [])}


def _baseline_sha256(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical(value: str) -> str:
    return CLASS_MAP.get(value, value if value else "error")


def _issue_for_entry(entry: dict, path: str) -> str:
    return entry.get("issue") or DEFAULT_ISSUE_BY_CLASS.get(entry["class"], "#187")


def validate_allowlist(entries: list[dict], today: date) -> list[str]:
    """Validate the structured exception contract without changing entries."""
    errors: list[str] = []
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        path_glob = entry.get("path_glob")
        if not path_glob or path_glob in {"*", "**"}:
            errors.append(f"{prefix}: path_glob must be path-scoped")
        for required in ("class", "reason", "owner"):
            if not entry.get(required):
                errors.append(f"{prefix}: missing {required}")
        expiry = entry.get("expiry")
        if expiry:
            try:
                if date.fromisoformat(expiry) < today:
                    errors.append(f"{prefix}: expired expiry {expiry}")
            except ValueError:
                errors.append(f"{prefix}: invalid expiry {expiry!r}")
        if entry.get("class") == "error":
            errors.append(f"{prefix}: error is not an allowlist classification")
    return errors


def build_manifest(
    occurrences: list[Occurrence],
    allowlist: list[dict],
    baseline_classification: dict[str, dict],
) -> dict:
    records: list[dict] = []
    for occurrence in occurrences:
        path, artifact = _bare_path(occurrence.path)
        entry = allowlist_match(path, occurrence.term, allowlist, date.today())
        baseline = baseline_classification.get(path, {})
        if entry is not None:
            context_class = entry["class"]
            classification = _canonical(context_class)
            reason = entry["reason"]
            owner = entry["owner"]
            issue = _issue_for_entry(entry, path)
            expiry = entry.get("expiry")
            generated = bool(entry.get("generated", False))
            source_of_generation = entry.get("source_of_generation")
        elif occurrence.klass == "baseline":
            context_class = "baseline"
            classification = _canonical(baseline.get("class", "error"))
            reason = baseline.get("reason", occurrence.reason)
            owner = baseline.get("owner")
            issue = baseline.get("owning_issue")
            expiry = None
            generated = classification == "generated-rebuild"
            source_of_generation = baseline.get("source_of_generation")
        else:
            context_class = occurrence.klass
            classification = _canonical(occurrence.klass)
            reason = occurrence.reason
            owner = None
            issue = "#187"
            expiry = None
            generated = False
            source_of_generation = None

        records.append({
            "path": occurrence.path,
            "line": occurrence.line if artifact == "source-tree" else None,
            "resource": path if artifact != "source-tree" else None,
            "token": occurrence.term,
            "context": occurrence.surface,
            "context_class": context_class,
            "surface": top_level_surface(path),
            "artifact": artifact,
            "origin": "generated" if generated or artifact != "source-tree" else "source",
            "source_of_generation": source_of_generation,
            "classification": classification,
            "reason": reason,
            "owner": owner,
            "issue": issue,
            "expiry": expiry,
        })

    return {
        "schema": "simplicio.rename-inventory/v1",
        "records": records,
        "total": len(records),
        "by_classification": dict(sorted(Counter(r["classification"] for r in records).items())),
        "by_surface": dict(sorted(Counter(r["surface"] for r in records).items())),
        "by_artifact": dict(sorted(Counter(r["artifact"] for r in records).items())),
    }


def validate_manifest(manifest: dict, allowlist_errors: list[str] | None = None) -> list[str]:
    errors = list(allowlist_errors or [])
    if manifest.get("schema") != "simplicio.rename-inventory/v1":
        errors.append("manifest: unsupported schema")
    for index, record in enumerate(manifest.get("records", [])):
        prefix = f"records[{index}]"
        for required in ("path", "token", "context_class", "surface", "artifact",
                         "origin", "classification", "reason", "owner", "issue"):
            if not record.get(required):
                errors.append(f"{prefix}: missing {required}")
        if record.get("classification") == "error":
            errors.append(f"{prefix}: unclassified/error occurrence")
        if record.get("artifact") == "source-tree" and not record.get("line"):
            errors.append(f"{prefix}: source occurrence missing line")
        if record.get("artifact") != "source-tree" and not record.get("resource"):
            errors.append(f"{prefix}: artifact occurrence missing resource")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    config = load_json(args.config, {"exclude_globs": []})
    allowlist = load_json(args.allowlist, {"entries": []})["entries"]
    baseline = load_json(args.baseline, {"counts": {}})["counts"]
    classification = _classification_data(args.classification)
    if args.wheel or args.sdist:
        occurrences: list[Occurrence] = []
        if args.wheel:
            occurrences += scan_archive(args.wheel, config, allowlist, baseline, date.today(), "wheel:")
        if args.sdist:
            occurrences += scan_archive(args.sdist, config, allowlist, baseline, date.today(), "sdist:")
    else:
        occurrences = scan(args.root, config, allowlist, baseline, date.today())
    manifest = build_manifest(occurrences, allowlist, classification)
    manifest["baseline"] = {
        "path": str(args.baseline),
        "sha256": _baseline_sha256(args.baseline),
    }
    errors = validate_manifest(manifest, validate_allowlist(allowlist, date.today()))
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"rename-inventory: {len(manifest['records'])} occurrences; errors={len(errors)}")
    if args.check and errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
