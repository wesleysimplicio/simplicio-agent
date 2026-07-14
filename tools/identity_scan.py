"""Fail-closed scan for legacy identity references.

The scanner is intentionally independent from the historical rename baseline:
it is suitable for a clean canonical surface and does not silently grandfather
new references.  Temporary compatibility is represented explicitly in a
manifest with an owner and expiry.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

IDENTITY_MANIFEST_SCHEMA = "simplicio.identity-legacy-manifest/v1"
IDENTITY_REPORT_SCHEMA = "simplicio.identity-scan/v1"
LEGACY_TERMS = ("hermes-agent", "hermes", "HERMES_")
_TERM_RE = re.compile(r"(?i)hermes(?:[-_ ]*agent)?")


@dataclass(frozen=True)
class IdentityFinding:
    path: str
    line: int
    term: str
    classification: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "term": self.term,
            "classification": self.classification,
            "reason": self.reason,
        }


def _today(value: date | str | None) -> date:
    if value is None:
        return date.today()
    return date.fromisoformat(value) if isinstance(value, str) else value


def validate_manifest(
    manifest: Mapping[str, Any], *, today: date | str | None = None
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != IDENTITY_MANIFEST_SCHEMA:
        errors.append(f"schema must be {IDENTITY_MANIFEST_SCHEMA}")
    if manifest.get("version") != 1:
        errors.append("version must be 1")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return errors + ["entries must be a list"]
    seen: set[tuple[str, str]] = set()
    current = _today(today)
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        if not isinstance(entry, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        term = str(entry.get("term", "")).strip()
        path_glob = str(entry.get("path_glob", "")).strip()
        if not term or not path_glob:
            errors.append(f"{prefix} requires term and path_glob")
        key = (term.casefold(), path_glob)
        if key in seen:
            errors.append(f"{prefix} duplicate term/path")
        seen.add(key)
        for field in ("owner", "reason"):
            if not str(entry.get(field, "")).strip():
                errors.append(f"{prefix}.{field} is required")
        expiry = entry.get("expiry")
        if expiry is not None:
            try:
                expiry_date = date.fromisoformat(str(expiry))
                if (
                    expiry_date < current
                    and entry.get("classification") != "legal_attribution"
                ):
                    errors.append(f"{prefix}.expiry is expired")
            except ValueError:
                errors.append(f"{prefix}.expiry must be YYYY-MM-DD")
        if entry.get("classification") not in {"compatibility", "legal_attribution"}:
            errors.append(
                f"{prefix}.classification must be compatibility or legal_attribution"
            )
    return sorted(set(errors))


def _entry_for(
    path: str, term: str, manifest: Mapping[str, Any], current: date
) -> Mapping[str, Any] | None:
    for entry in manifest.get("entries", []):
        if not isinstance(entry, Mapping) or not fnmatch.fnmatch(
            path, str(entry.get("path_glob", ""))
        ):
            continue
        configured = str(entry.get("term", ""))
        if (
            configured
            and configured.casefold() not in term.casefold()
            and term.casefold() not in configured.casefold()
        ):
            continue
        expiry = entry.get("expiry")
        if expiry and date.fromisoformat(str(expiry)) < current:
            return {"expired": True, **entry}
        return entry
    return None


def scan_text(
    path: str,
    text: str,
    manifest: Mapping[str, Any],
    *,
    today: date | str | None = None,
) -> list[IdentityFinding]:
    current = _today(today)
    findings: list[IdentityFinding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for match in _TERM_RE.finditer(line):
            term = match.group(0)
            entry = _entry_for(path, term, manifest, current)
            if entry and not entry.get("expired"):
                classification = str(entry.get("classification", "compatibility"))
                reason = str(entry.get("reason", "manifested legacy reference"))
            elif entry and entry.get("expired"):
                classification, reason = "expired", "manifest entry has expired"
            else:
                classification, reason = "legacy", "not declared in identity manifest"
            findings.append(
                IdentityFinding(path, line_number, term, classification, reason)
            )
    return findings


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line]


def scan(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    today: date | str | None = None,
    paths: list[str] | None = None,
    exclude_globs: tuple[str, ...] = (
        ".git/*",
        ".simplicio/*",
        ".orchestrator/*",
        "node_modules/*",
    ),
) -> list[IdentityFinding]:
    findings: list[IdentityFinding] = []
    selected = paths if paths is not None else tracked_files(root)
    for rel_path in selected:
        normalized = rel_path.replace("\\", "/")
        if any(fnmatch.fnmatch(normalized, pattern) for pattern in exclude_globs):
            continue
        path = root / rel_path
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(normalized, text, manifest, today=today))
    return findings


def report(
    findings: list[IdentityFinding], *, root: Path | None = None
) -> dict[str, Any]:
    blocking = [
        item for item in findings if item.classification in {"legacy", "expired"}
    ]
    return {
        "schema": IDENTITY_REPORT_SCHEMA,
        "ok": not blocking,
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "digest": "sha256:"
        + hashlib.sha256(
            json.dumps([f.to_dict() for f in findings], sort_keys=True).encode()
        ).hexdigest(),
        "findings": [item.to_dict() for item in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        help="scan only this root-relative path; repeatable",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="fail when any undeclared or expired legacy reference is found",
    )
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest)
    if errors:
        print(
            json.dumps(
                {"schema": IDENTITY_REPORT_SCHEMA, "ok": False, "errors": errors},
                sort_keys=True,
            )
        )
        return 2
    result = report(scan(args.root, manifest, paths=args.paths), root=args.root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for finding in result["findings"]:
            if finding["classification"] in {"legacy", "expired"}:
                print(
                    f"{finding['path']}:{finding['line']}: {finding['classification']} {finding['term']}"
                )
        print(f"identity-scan: {result['blocking_count']} blocking finding(s)")
    return 1 if args.no_legacy and not result["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
