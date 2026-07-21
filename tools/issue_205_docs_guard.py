#!/usr/bin/env python3
"""Guard the user-facing documentation scope for issue #205.

The repository-wide rename guard intentionally has broader historical and
internal classifications. This focused guard makes the issue's boundary
machine-readable: every legacy token in the five entry documents must match
an explicit, path-aware exception in ``docs/rename-inventory-issue-205.json``.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LEGACY = re.compile(r"\bhermes(?:\s+turbo)?(?:\s+agent)?\b|\bhermes-agent\b", re.IGNORECASE)
INVENTORY = Path(__file__).resolve().parent.parent / "docs/rename-inventory-issue-205.json"


def load_inventory(path: Path = INVENTORY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scan(root: Path, inventory: dict | None = None) -> list[dict[str, object]]:
    inventory = inventory or load_inventory()
    rules = inventory["allowlist"]
    findings: list[dict[str, object]] = []
    for rel_path in inventory["scope"]:
        path = root / rel_path
        rules_for_path = [rule for rule in rules if rule["path"] == rel_path]
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in LEGACY.finditer(line):
                if any(re.search(rule["pattern"], line, re.IGNORECASE) for rule in rules_for_path):
                    continue
                findings.append({
                    "path": rel_path,
                    "line": line_no,
                    "match": match.group(0),
                    "evidence": line.strip(),
                })
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    inventory = load_inventory()
    findings = scan(args.root, inventory)
    report = {
        "schema": "simplicio.issue-205-docs-guard/v1",
        "issue": inventory["issue"],
        "scope": inventory["scope"],
        "finding_count": len(findings),
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(f"{finding['path']}:{finding['line']}: {finding['evidence']}")
        print(f"issue-205-docs-guard: {len(findings)} unallowlisted occurrence(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
