"""Shared ADR registry parsing and validation helpers."""

from __future__ import annotations

import re
from pathlib import Path

ADR_NAME = re.compile(r"^ADR-(?P<number>\d{4})-(?P<slug>[a-z0-9][a-z0-9-]*)\.md$")
_HEADING = re.compile(r"^#\s+(?P<title>.+?)\s*$")
_FIELD = re.compile(
    r"^(?:[-*]\s*)?(?:\*\*)?(?P<key>status|date):(?:\*\*)?\s*"
    r"(?P<value>.+?)\s*$",
    re.IGNORECASE,
)


def iter_adrs(root: Path) -> list[dict[str, str | int]]:
    """Return parsed ADR metadata in deterministic filename order."""
    entries: list[dict[str, str | int]] = []
    for path in sorted(root.glob("ADR-*.md")):
        match = ADR_NAME.fullmatch(path.name)
        if not match:
            entries.append({"path": path.name, "error": "invalid filename"})
            continue
        title = ""
        status = ""
        date = ""
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not title and (heading := _HEADING.match(raw)):
                title = heading.group("title")
            if field := _FIELD.match(raw.strip()):
                key = field.group("key").lower()
                if key == "status":
                    status = field.group("value")
                elif key == "date":
                    date = field.group("value")
        entries.append({
            "number": int(match.group("number")),
            "slug": match.group("slug"),
            "path": path.name,
            "title": title or match.group("slug").replace("-", " ").title(),
            "status": status or "unspecified",
            "date": date or "unspecified",
        })
    return entries


def validate(
    entries: list[dict[str, str | int]], *, require_index: Path | None = None
) -> list[str]:
    """Return stable, human-readable registry violations."""
    errors: list[str] = []
    by_number: dict[int, list[str]] = {}
    for entry in entries:
        if "error" in entry:
            errors.append(f"{entry['path']}: {entry['error']}")
            continue
        by_number.setdefault(int(entry["number"]), []).append(str(entry["path"]))
    for number, paths in sorted(by_number.items()):
        if len(paths) > 1:
            errors.append(f"ADR-{number:04d}: duplicate files: {', '.join(paths)}")
    if require_index is not None:
        expected = {str(entry["path"]) for entry in entries if "error" not in entry}
        actual = set(
            re.findall(
                r"\((ADR-\d{4}-[a-z0-9-]+\.md)\)",
                require_index.read_text(encoding="utf-8"),
            )
        )
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        errors.extend(f"index missing {path}" for path in missing)
        errors.extend(f"index references unknown {path}" for path in extra)
    return errors
