#!/usr/bin/env python3
"""Audit JSON use against the exact boundary inventory.

The baseline mode is intentionally non-blocking while the Runtime publishes
HBI v1. Strict mode is the release gate: every finding must be an explicit
exception or already migrated to HBP/HBI/TOML. Paths in the inventory are
exact; glob entries are rejected.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib
import tarfile
import zipfile
from collections.abc import Iterable
from typing import Any

TOKENS = re.compile(
    r"(?:import\s+json|from\s+json\s+import|json\.(?:loads|dumps|load|dump)|"
    r"JSON\.(?:parse|stringify)|serde_json|\.jsonl?\b|\.ndjson\b|jsonrpc)",
    re.IGNORECASE,
)
SKIP = {".git", "node_modules", "target", "dist", "build", ".venv", "__pycache__", ".orchestrator"}
SOURCE_SUFFIXES = {".py", ".mjs", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".cs"}
QUALITY_SCHEMA = "simplicio-agent.json-boundary-quality/v1"
PACKAGE_UNAVAILABLE_REASON = "package artifact was not provided"
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"(?<!:)//[^\r\n]*|^\s*#[^\r\n]*", re.MULTILINE)


def _without_comments(text: str) -> str:
    """Keep executable text while avoiding comment-only JSON false positives."""
    text = BLOCK_COMMENT.sub(lambda match: "".join("\n" if char == "\n" else " " for char in match.group()), text)
    return LINE_COMMENT.sub(lambda match: "".join("\n" if char == "\n" else " " for char in match.group()), text)


def _findings_in_text(path: str, text: str) -> list[tuple[str, int, str]]:
    return [
        (path, text.count("\n", 0, match.start()) + 1, match.group(0))
        for match in TOKENS.finditer(_without_comments(text))
    ]


def load_inventory(path: pathlib.Path) -> dict[str, dict]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    # v1 inventories may group exact paths under [[boundary]]/[[audit]].
    # Expand those groups into the same normalized map used by the scanner.
    groups = list(raw.get("boundary", [])) + list(raw.get("audit", []))
    for group in groups:
        names = group.get("paths") or ([group["path"]] if group.get("path") else [])
        target = group.get("target_format", "")
        status = group.get("status") or (
            "exception" if target.lower().startswith(("preserve", "json-rpc", "external", "signed", "cyclonedx"))
            else "migration_pending"
        )
        entry = {
            **group,
            "status": status,
            "reason": group.get("reason") or group.get("rationale") or group.get("lifecycle", ""),
            "expires": group.get("expires") or ("2099-12-31" if status == "exception" else "2026-12-31"),
        }
        for name in names:
            if not name or any(ch in name for ch in "*?[]"):
                raise ValueError(f"inventory path must be exact: {name!r}")
            if name in result:
                raise ValueError(f"duplicate inventory path: {name}")
            for field in ("owner", "reason", "expires", "category", "target_format", "status"):
                if not entry.get(field):
                    raise ValueError(f"{name}: missing {field}")
            try:
                dt.date.fromisoformat(entry["expires"])
            except ValueError as exc:
                raise ValueError(f"{name}: invalid expires date") from exc
            result[name] = entry
    return result


def findings(root: pathlib.Path) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        paths = [pathlib.Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]
        for relative in paths:
            if (
                any(part in SKIP for part in relative.parts)
                or relative.suffix.lower() not in SOURCE_SUFFIXES
                or relative.as_posix() == "scripts/check_json_boundaries.py"
            ):
                continue
            path = root / relative
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            out.extend(_findings_in_text(relative.as_posix(), text))
        return out
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories
            if name not in SKIP and not (pathlib.Path(current) / name).is_symlink()
        )
        for name in sorted(names):
            path = pathlib.Path(current) / name
            rel_path = path.relative_to(root)
            if path.suffix.lower() not in SOURCE_SUFFIXES or rel_path.as_posix() == "scripts/check_json_boundaries.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            out.extend(_findings_in_text(rel_path.as_posix(), text))
    return out


def _package_member_names(package: pathlib.Path) -> Iterable[tuple[str, bytes]]:
    """Yield source members from a directory or archive without extracting it."""
    if package.is_dir():
        for path in sorted(package.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in SOURCE_SUFFIXES:
                yield path.relative_to(package).as_posix(), path.read_bytes()
        return
    if not package.is_file():
        raise FileNotFoundError(str(package))
    if zipfile.is_zipfile(package):
        with zipfile.ZipFile(package) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                name = pathlib.PurePosixPath(info.filename)
                if info.is_dir() or name.is_absolute() or ".." in name.parts:
                    continue
                if pathlib.Path(info.filename).suffix.lower() in SOURCE_SUFFIXES:
                    yield name.as_posix(), archive.read(info)
        return
    if tarfile.is_tarfile(package):
        with tarfile.open(package) as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                name = pathlib.PurePosixPath(member.name)
                if not member.isfile() or name.is_absolute() or ".." in name.parts:
                    continue
                if pathlib.Path(member.name).suffix.lower() in SOURCE_SUFFIXES:
                    handle = archive.extractfile(member)
                    if handle is not None:
                        yield name.as_posix(), handle.read()
        return
    raise ValueError(f"unsupported package artifact: {package}")


def package_findings(package: pathlib.Path) -> list[tuple[str, int, str]]:
    """Scan package contents using the same token rules as the source scanner."""
    out: list[tuple[str, int, str]] = []
    for name, payload in _package_member_names(package):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        out.extend(_findings_in_text(name, text))
    return out


def _classify(
    matches: Iterable[tuple[str, int, str]], inventory: dict[str, dict]
) -> dict[str, Any]:
    unknown: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for path, line, token in matches:
        item = {"path": path, "line": line, "token": token}
        entry = inventory.get(path)
        if entry is None:
            unknown.append(item)
        elif dt.date.fromisoformat(entry["expires"]) < dt.date.today():
            expired.append(item)
        elif entry["status"] == "migration_pending":
            pending.append(item)
        else:
            exceptions.append({**item, "reason": entry["reason"], "owner": entry["owner"]})
    blocking = [*unknown, *pending, *expired]
    return {
        "ok": not blocking,
        "finding_count": len(blocking),
        "unknown": unknown,
        "pending": pending,
        "expired": expired,
        "exceptions": exceptions,
    }


def quality_report(
    root: pathlib.Path,
    inventory_path: pathlib.Path,
    *,
    packages: Iterable[pathlib.Path] = (),
    require_package: bool = False,
) -> dict[str, Any]:
    """Build a release-quality report with explicit unavailable evidence."""
    inventory = load_inventory(inventory_path)
    source = _classify(findings(root), inventory)
    package_paths = tuple(packages)
    package_results: list[dict[str, Any]] = []
    package_errors: list[str] = []
    for package in package_paths:
        try:
            classified = _classify(package_findings(package), inventory)
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            package_errors.append(f"{package}: {exc}")
            continue
        package_results.append({"artifact": str(package), **classified})
    if not package_paths:
        package_evidence: dict[str, Any] = {
            "value": None,
            "reason": PACKAGE_UNAVAILABLE_REASON,
        }
    elif package_errors:
        package_evidence = {"value": None, "reason": "; ".join(package_errors)}
    else:
        package_evidence = {"value": package_results, "reason": None}
    package_ok = bool(package_results) and not package_errors and all(
        result["ok"] for result in package_results
    )
    ok = source["ok"] and (package_ok if require_package else not package_errors)
    return {
        "schema": QUALITY_SCHEMA,
        "ok": ok,
        "status": "pass" if ok else "block",
        "evidence": {
            "source": {"value": source, "reason": None},
            "package": package_evidence,
        },
        "source": source,
        "packages": package_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).parents[1])
    parser.add_argument("--inventory", type=pathlib.Path)
    parser.add_argument("--mode", choices=("baseline", "strict", "release"), default="baseline")
    parser.add_argument("--package", dest="packages", action="append", type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--max-findings", type=int, default=50)
    args = parser.parse_args()
    inventory_path = args.inventory or args.root / "config" / "json-boundaries.toml"
    try:
        inventory = load_inventory(inventory_path)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"inventory error: {exc}", file=sys.stderr)
        return 2
    packages = tuple(args.packages or ())
    if args.mode == "release" or packages:
        report = quality_report(
            args.root,
            inventory_path,
            packages=packages,
            require_package=args.mode == "release",
        )
        if args.report:
            args.report.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(
            f"json-boundaries: status={report['status']} "
            f"source_findings={report['source']['finding_count']} "
            f"packages={len(report['packages'])}"
        )
        if report["evidence"]["package"]["value"] is None:
            print(f"UNAVAILABLE package: {report['evidence']['package']['reason']}")
        for item in report["source"]["unknown"][: max(0, args.max_findings)]:
            print(f"UNCLASSIFIED {item['path']}:{item['line']}: {item['token']}")
        for category in ("pending", "expired"):
            for item in report["source"][category][: max(0, args.max_findings)]:
                print(f"{category.upper()} {item['path']}:{item['line']}: {item['token']}")
        for package in report["packages"]:
            for item in package["unknown"][: max(0, args.max_findings)]:
                print(f"UNCLASSIFIED package:{item['path']}:{item['line']}: {item['token']}")
        return 0 if report["ok"] or args.mode == "baseline" else 1
    unknown: list[tuple[str, int, str]] = []
    pending: list[tuple[str, int, str]] = []
    expired: list[str] = []
    today = dt.date.today()
    for path, line, token in findings(args.root):
        entry = inventory.get(path)
        if entry is None:
            unknown.append((path, line, token))
        elif dt.date.fromisoformat(entry["expires"]) < today:
            expired.append(path)
        elif entry["status"] == "migration_pending":
            pending.append((path, line, token))
    print(f"json-boundaries: findings={len(unknown)+len(pending)} unknown={len(unknown)} pending={len(pending)} expired={len(expired)}")
    for path, line, token in unknown[: max(0, args.max_findings)]:
        print(f"UNCLASSIFIED {path}:{line}: {token}")
    for path in expired:
        print(f"EXPIRED {path}")
    if args.mode == "strict" and (unknown or pending or expired):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
