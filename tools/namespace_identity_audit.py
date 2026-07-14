"""Deterministic namespace and identity migration audit.

This audit is intentionally evidence-only.  It searches consumers of both the
canonical and legacy names, validates a reviewed inventory of canonical
surfaces/shims/bridges, and combines source, package, and runtime observations
into a content-addressed receipt.  It does not rename files or update the
inventory when a finding is observed.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

AUDIT_SCHEMA = "simplicio.namespace-identity-audit/v1"
INVENTORY_SCHEMA = "simplicio.namespace-identity-inventory/v1"
RECEIPT_SCHEMA = "simplicio.namespace-identity-receipt/v1"
INVENTORY_VERSION = 1
_DEFAULT_EXCLUDES = (".git/*", ".orchestrator/*", ".simplicio/*", "node_modules/*")
_BINARY_SUFFIXES = {
    ".7z",
    ".a",
    ".db",
    ".dll",
    ".dylib",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".parquet",
    ".png",
    ".pyc",
    ".so",
    ".sqlite",
    ".tar",
    ".wasm",
    ".webp",
    ".whl",
    ".zip",
}


@dataclass(frozen=True)
class InventoryEntry:
    name: str
    kind: str
    path_glob: str
    owner: str
    reason: str
    canonical: str | None = None
    expiry: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    surface: str
    path: str
    line: int
    term: str
    kind: str
    classification: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _today(value: date | str | None) -> date:
    if value is None:
        return date.today()
    return date.fromisoformat(value) if isinstance(value, str) else value


def load_inventory(path: str | Path) -> dict[str, Any]:
    """Load the JSON inventory without applying defaults or mutation."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def inventory_entries(inventory: Mapping[str, Any]) -> tuple[InventoryEntry, ...]:
    entries = inventory.get("entries", [])
    return tuple(
        InventoryEntry(
            name=str(item.get("name", "")).strip(),
            kind=str(item.get("kind", "")).strip(),
            path_glob=str(item.get("path_glob", "")).strip(),
            owner=str(item.get("owner", "")).strip(),
            reason=str(item.get("reason", "")).strip(),
            canonical=(
                str(item["canonical"]).strip() if item.get("canonical") else None
            ),
            expiry=(str(item["expiry"]).strip() if item.get("expiry") else None),
        )
        for item in entries
        if isinstance(item, Mapping)
    )


def validate_inventory(
    inventory: Mapping[str, Any], *, today: date | str | None = None
) -> list[str]:
    """Validate shape, ownership, and time-bounded bridge declarations."""

    errors: list[str] = []
    if inventory.get("schema") != INVENTORY_SCHEMA:
        errors.append(f"schema must be {INVENTORY_SCHEMA}")
    if inventory.get("version") != INVENTORY_VERSION:
        errors.append(f"version must be {INVENTORY_VERSION}")
    names = inventory.get("canonical_names")
    if not isinstance(names, Mapping) or not names:
        errors.append("canonical_names must be a non-empty object")
    else:
        for name, value in names.items():
            if not str(name).strip() or not str(value).strip():
                errors.append(
                    "canonical_names entries require non-empty names and values"
                )
    raw_entries = inventory.get("entries")
    if not isinstance(raw_entries, list):
        return sorted(set(errors + ["entries must be a list"]))
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, Mapping):
            errors.append(f"entries[{index}] must be an object")

    current = _today(today)
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(inventory_entries(inventory)):
        prefix = f"entries[{index}]"
        key = (entry.name.casefold(), entry.path_glob)
        if key in seen:
            errors.append(f"{prefix} duplicate name/path")
        seen.add(key)
        if not entry.name or not entry.path_glob:
            errors.append(f"{prefix} requires name and path_glob")
        if entry.kind not in {"canonical", "shim", "bridge", "legacy_surface"}:
            errors.append(f"{prefix}.kind is invalid")
        for field, value in (("owner", entry.owner), ("reason", entry.reason)):
            if not value:
                errors.append(f"{prefix}.{field} is required")
        if entry.kind in {"shim", "bridge"} and not entry.expiry:
            errors.append(f"{prefix}.expiry is required for {entry.kind}")
        if entry.expiry:
            try:
                expiry = date.fromisoformat(entry.expiry)
            except ValueError:
                errors.append(f"{prefix}.expiry must be YYYY-MM-DD")
            else:
                if expiry < current and entry.kind in {"shim", "bridge"}:
                    errors.append(f"{prefix}.expiry is expired")
        if entry.kind in {"shim", "bridge"} and not entry.canonical:
            errors.append(f"{prefix}.canonical is required for {entry.kind}")
    return sorted(set(errors))


def _terms(inventory: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return deterministic ``(term, kind)`` pairs used by every surface."""

    names = inventory.get("canonical_names", {})
    result: list[tuple[str, str]] = []
    for value in names.values() if isinstance(names, Mapping) else ():
        text = str(value).strip()
        if text:
            result.append((text, "canonical"))
    legacy = inventory.get("legacy_names", [])
    for value in legacy if isinstance(legacy, list) else ():
        text = str(value).strip()
        if text:
            result.append((text, "legacy"))
    # Longest first prevents ``hermes`` from hiding ``hermes-agent`` in a line.
    return tuple(
        sorted(
            set(result), key=lambda item: (-len(item[0]), item[0].casefold(), item[1])
        )
    )


def _entry_for(path: str, entries: Iterable[InventoryEntry]) -> InventoryEntry | None:
    matches = [entry for entry in entries if fnmatch.fnmatch(path, entry.path_glob)]
    return (
        sorted(
            matches, key=lambda entry: (len(entry.path_glob), entry.name), reverse=True
        )[0]
        if matches
        else None
    )


def _iter_paths(root: Path, paths: list[str] | None) -> list[str]:
    if paths is not None:
        return sorted({path.replace("\\", "/") for path in paths})
    try:
        output = subprocess.run(
            ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
        return sorted(line.replace("\\", "/") for line in output.splitlines() if line)
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )


def _read_text(path: Path) -> str | None:
    if path.suffix.casefold() in _BINARY_SUFFIXES:
        return None
    try:
        raw = path.read_bytes()
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _findings_in_text(
    text: str,
    *,
    surface: str,
    path: str,
    inventory: Mapping[str, Any],
) -> list[Finding]:
    entries = inventory_entries(inventory)
    patterns = tuple(
        (
            term,
            kind,
            re.compile(re.escape(term), re.IGNORECASE if kind == "legacy" else 0),
        )
        for term, kind in _terms(inventory)
    )
    findings: list[Finding] = []
    path_entry = _entry_for(path, entries)
    for line_number, line in enumerate(text.splitlines(), 1):
        matches: list[tuple[int, int, str, str]] = []
        for term, kind, pattern in patterns:
            for match in pattern.finditer(line):
                matches.append((match.start(), match.end(), term, kind))
        for _, _, term, kind in sorted(
            matches,
            key=lambda item: (item[0], -(item[1] - item[0]), item[2].casefold()),
        ):
            if kind == "canonical":
                classification, reason = "canonical", "canonical consumer"
            elif path_entry and path_entry.kind in {"shim", "bridge"}:
                classification, reason = path_entry.kind, path_entry.reason
            elif path_entry and path_entry.kind == "legacy_surface":
                classification, reason = "legacy_surface", path_entry.reason
            else:
                classification, reason = (
                    "unclassified_legacy",
                    "legacy name outside an inventoried shim or bridge",
                )
            findings.append(
                Finding(surface, path, line_number, term, kind, classification, reason)
            )
    return findings


def search_consumers(
    root: Path,
    inventory: Mapping[str, Any],
    *,
    paths: list[str] | None = None,
    surface: str = "source",
) -> list[Finding]:
    """Search tracked/text files for canonical and legacy name consumers."""

    findings: list[Finding] = []
    for rel_path in _iter_paths(root, paths):
        if any(fnmatch.fnmatch(rel_path, pattern) for pattern in _DEFAULT_EXCLUDES):
            continue
        text = _read_text(root / rel_path)
        if text is not None:
            findings.extend(
                _findings_in_text(
                    text, surface=surface, path=rel_path, inventory=inventory
                )
            )
    return sorted(
        findings, key=lambda item: (item.surface, item.path, item.line, item.term)
    )


def scan_source(
    root: Path, inventory: Mapping[str, Any], *, paths: list[str] | None = None
) -> list[Finding]:
    return search_consumers(root, inventory, paths=paths, surface="source")


def _archive_members(path: Path) -> list[tuple[str, bytes]]:
    name = path.name.casefold()
    if name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(path) as archive:
            return [
                (info.filename, archive.read(info))
                for info in archive.infolist()
                if not info.is_dir()
            ]
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(path, "r:*") as archive:
            members: list[tuple[str, bytes]] = []
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is not None:
                    members.append((info.name, handle.read()))
            return members
    raise ValueError(f"unsupported build artifact: {path}")


def scan_build(
    artifacts: Iterable[Path], inventory: Mapping[str, Any]
) -> list[Finding]:
    findings: list[Finding] = []
    for artifact in sorted(
        (Path(path) for path in artifacts), key=lambda path: path.as_posix()
    ):
        for member, raw in _archive_members(artifact):
            if Path(member).suffix.casefold() in _BINARY_SUFFIXES:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            findings.extend(
                _findings_in_text(
                    text,
                    surface="build",
                    path=f"{artifact.name}:{member.replace(chr(92), '/')}",
                    inventory=inventory,
                )
            )
    return sorted(findings, key=lambda item: (item.path, item.line, item.term))


def _runtime_values(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            yield from _runtime_values(value[key], f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _runtime_values(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def scan_runtime(
    snapshot: Mapping[str, Any] | str, inventory: Mapping[str, Any]
) -> list[Finding]:
    """Scan a redacted runtime snapshot; secrets must not be supplied."""

    value: Any = snapshot
    if isinstance(snapshot, str):
        value = json.loads(snapshot)
    findings: list[Finding] = []
    for path, text in _runtime_values(value):
        findings.extend(
            _findings_in_text(text, surface="runtime", path=path, inventory=inventory)
        )
    return sorted(findings, key=lambda item: (item.path, item.line, item.term))


def _section(findings: list[Finding]) -> dict[str, Any]:
    rows = [finding.to_dict() for finding in findings]
    blocking = [
        finding
        for finding in findings
        if finding.classification == "unclassified_legacy"
    ]
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    return {
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "by_classification": dict(sorted(counts.items())),
        "digest": "sha256:"
        + hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "findings": rows,
    }


def build_receipt(
    inventory: Mapping[str, Any],
    *,
    source: list[Finding] | None = None,
    build: list[Finding] | None = None,
    runtime: list[Finding] | None = None,
    inventory_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Combine available surfaces without treating omitted surfaces as clean."""

    sections: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, findings in (("source", source), ("build", build), ("runtime", runtime)):
        if findings is None:
            missing.append(name)
        else:
            sections[name] = _section(findings)
    errors = sorted(set(inventory_errors or []))
    blocking = sum(section["blocking_count"] for section in sections.values())
    remaining_entries = sorted(
        entry.name
        for entry in inventory_entries(inventory)
        if entry.kind in {"shim", "bridge", "legacy_surface"}
    )
    migration_scope = (
        "VERIFIED"
        if not missing and not blocking and not errors and not remaining_entries
        else "UNVERIFIED"
    )
    body = {
        "schema": RECEIPT_SCHEMA,
        "inventory_schema": inventory.get("schema"),
        "inventory_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "migration_scope": migration_scope,
        "remaining_migration_entries": remaining_entries,
        "unverified_surfaces": missing,
        "inventory_errors": errors,
        "sections": sections,
    }
    body["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    return body


def audit(
    root: Path,
    inventory: Mapping[str, Any],
    *,
    artifacts: Iterable[Path] = (),
    runtime_snapshot: Mapping[str, Any] | str | None = None,
    paths: list[str] | None = None,
    today: date | str | None = None,
) -> dict[str, Any]:
    errors = validate_inventory(inventory, today=today)
    source = scan_source(root, inventory, paths=paths)
    build = scan_build(artifacts, inventory) if artifacts else None
    runtime = (
        scan_runtime(runtime_snapshot, inventory)
        if runtime_snapshot is not None
        else None
    )
    return build_receipt(
        inventory, source=source, build=build, runtime=runtime, inventory_errors=errors
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument(
        "--build", dest="artifacts", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--runtime", type=Path, default=None, help="redacted JSON runtime snapshot"
    )
    parser.add_argument("--path", dest="paths", action="append")
    parser.add_argument("--today", default=None, help="evaluation date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    inventory = load_inventory(args.inventory)
    runtime = (
        None
        if args.runtime is None
        else json.loads(args.runtime.read_text(encoding="utf-8"))
    )
    result = audit(
        args.root,
        inventory,
        artifacts=args.artifacts,
        runtime_snapshot=runtime,
        paths=args.paths,
        today=args.today,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"namespace-identity-audit: {result['migration_scope']} "
            f"digest={result['digest']}"
        )
        for section in result["sections"].values():
            for finding in section["findings"]:
                if finding["classification"] == "unclassified_legacy":
                    print(
                        f"{finding['surface']}:{finding['path']}:{finding['line']}: "
                        f"{finding['term']}"
                    )
    return (
        1
        if result["inventory_errors"]
        or any(section["blocking_count"] for section in result["sections"].values())
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
