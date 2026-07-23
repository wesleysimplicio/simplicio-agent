"""Bounded, fail-closed inventory check for repository JSON boundaries."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

import tomllib


class InventoryError(ValueError):
    """Raised when the exception registry is unsafe or malformed."""


@dataclass(frozen=True)
class ExceptionEntry:
    path: str
    category: str
    owner: str
    rationale: str
    expires_at: str


@dataclass(frozen=True)
class ScanResult:
    candidates: tuple[str, ...]
    exceptions: tuple[ExceptionEntry, ...]
    findings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "target",
    ".venv",
}


def _exact_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InventoryError(f"{field} must be a non-empty path")
    if "\\" in value or any(char in value for char in "*?[]"):
        raise InventoryError(f"{field} must be an exact POSIX path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise InventoryError(f"{field} must be normalized and relative: {value!r}")
    return value


def _required_text(group: dict[str, object], key: str, path: str) -> str:
    value = group.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{path}: missing {key}")
    return value.strip()


def load_inventory(
    path: Path, today: dt.date | None = None
) -> tuple[tuple[str, ...], tuple[str, ...], int, int, tuple[ExceptionEntry, ...]]:
    """Load and validate exact exception entries from a TOML registry."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "simplicio-agent.json-boundaries/v1":
        raise InventoryError("unsupported inventory format")

    reviewed_at = data.get("reviewed_at")
    expires_at = data.get("expires_at")
    if not isinstance(reviewed_at, str) or not isinstance(expires_at, str):
        raise InventoryError("inventory requires reviewed_at and expires_at")
    try:
        dt.date.fromisoformat(reviewed_at)
        expiry = dt.date.fromisoformat(expires_at)
    except ValueError as exc:
        raise InventoryError("reviewed_at and expires_at must be ISO dates") from exc
    if (today or dt.date.today()) > expiry:
        raise InventoryError(f"inventory expired on {expires_at}")

    extensions = data.get("source_extensions")
    if not isinstance(extensions, list) or not extensions or any(
        not isinstance(item, str) or not item.startswith(".") for item in extensions
    ):
        raise InventoryError("source_extensions must contain file extensions")
    roots = data.get("scan_roots")
    if not isinstance(roots, list) or not roots:
        raise InventoryError("scan_roots must contain exact relative roots")
    scan_roots = tuple(_exact_relative_path(root, "scan_roots entry") for root in roots)

    max_files = data.get("max_files")
    max_bytes = data.get("max_bytes")
    if not isinstance(max_files, int) or max_files < 1 or not isinstance(max_bytes, int) or max_bytes < 1:
        raise InventoryError("max_files and max_bytes must be positive integers")

    entries: list[ExceptionEntry] = []
    seen: set[str] = set()
    for index, group in enumerate(data.get("boundary", [])):
        if not isinstance(group, dict):
            raise InventoryError(f"boundary[{index}] must be a table")
        category = _required_text(group, "category_id", f"boundary[{index}]")
        owner = _required_text(group, "owner", f"boundary[{index}]")
        rationale = _required_text(group, "rationale", f"boundary[{index}]")
        paths = group.get("paths")
        if not isinstance(paths, list) or not paths:
            raise InventoryError(f"boundary[{index}]: paths must be non-empty")
        for raw_path in paths:
            exact_path = _exact_relative_path(raw_path, f"boundary[{index}].paths")
            if exact_path in seen:
                raise InventoryError(f"duplicate exception path: {exact_path}")
            seen.add(exact_path)
            entries.append(ExceptionEntry(exact_path, category, owner, rationale, expires_at))
    return scan_roots, tuple(extensions), max_files, max_bytes, tuple(entries)


def _files_under(root: Path, scan_roots: Iterable[str], extensions: tuple[str, ...], max_files: int, max_bytes: int) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative_root in scan_roots:
        directory = (root / Path(*PurePosixPath(relative_root).parts)).resolve()
        if not directory.is_dir():
            raise InventoryError(f"scan root does not exist: {relative_root}")
        for current, directories, names in os.walk(directory):
            directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
            for name in sorted(names):
                candidate = Path(current) / name
                if candidate.suffix.lower() not in extensions:
                    continue
                if len(files) >= max_files:
                    raise InventoryError(f"scan exceeded max_files={max_files}")
                if candidate.stat().st_size > max_bytes:
                    relative = candidate.relative_to(root).as_posix()
                    raise InventoryError(f"scan exceeded max_bytes={max_bytes}: {relative}")
                files.append(candidate)
    return tuple(sorted(set(files)))


def scan(root: Path, inventory_path: Path) -> ScanResult:
    scan_roots, extensions, max_files, max_bytes, exceptions = load_inventory(inventory_path)
    files = _files_under(root, scan_roots, extensions, max_files, max_bytes)
    by_path = {entry.path: entry for entry in exceptions}
    candidates = tuple(file.relative_to(root).as_posix() for file in files)
    findings = tuple(path for path in candidates if path not in by_path)
    missing = tuple(path for path in by_path if not (root / Path(*PurePosixPath(path).parts)).is_file())
    return ScanResult(candidates, exceptions, tuple(sorted((*findings, *[f"stale exception: {path}" for path in missing]))))


def render_markdown(result: ScanResult, inventory_path: Path) -> str:
    status = "PASS" if result.passed else "FAIL"
    categories: dict[str, int] = {}
    for entry in result.exceptions:
        categories[entry.category] = categories.get(entry.category, 0) + 1
    lines = [
        "# Internal JSON boundary scan",
        "",
        f"- Status: **{status}**",
        f"- Candidate files: **{len(result.candidates)}**",
        f"- Exact exceptions: **{len(result.exceptions)}**",
        f"- Unclassified findings: **{len(result.findings)}**",
        f"- Registry: `{inventory_path.as_posix()}`",
        "",
        "## Exception categories",
        "",
        "| Category | Exact paths |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{category}` | {count} |" for category, count in sorted(categories.items()))
    lines.extend(["", "## Findings", ""])
    if result.findings:
        lines.extend(f"- `{finding}`" for finding in result.findings)
    else:
        lines.append("- None. Every bounded candidate has an exact registry entry.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--inventory", type=Path, default=Path("config/json-boundaries.toml"))
    args = parser.parse_args(argv)
    try:
        result = scan(args.root.resolve(), args.inventory.resolve())
    except (OSError, InventoryError) as exc:
        print(f"FAIL| {exc}", file=sys.stderr)
        return 2
    print(render_markdown(result, args.inventory))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
