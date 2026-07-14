"""Validate the Native/P0 reconciliation graph and its local issue-body snapshot.

The GitHub issue bodies are intentionally not treated as source code.  The
checked-in YAML manifest is the source of truth for the graph; a body snapshot
can be supplied to prove that the public execution map has not drifted.  A
read-only GitHub check is available with ``--github-repo`` when credentials and
network access are present.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

EXPECTED_EPIC = 314
EXPECTED_P0_ISSUES = (209, 210, 211, 220, 221, 222, 228)
NATIVE_ISSUES = frozenset(range(315, 324))
VALID_RELATIONS = frozenset({"prerequisite", "subordinate", "superseded"})
START_MARKER = "<!-- native-p0-reconciliation:start -->"
END_MARKER = "<!-- native-p0-reconciliation:end -->"


class DuplicateKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that does not silently discard duplicate keys."""


def _construct_mapping(
    loader: DuplicateKeyLoader, node: yaml.MappingNode, deep: bool = False
):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a manifest and preserve duplicate-key failures for the gate."""
    with path.open(encoding="utf-8") as stream:
        value = yaml.load(stream, Loader=DuplicateKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("manifest root must be a mapping")
    return value


def _issue_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.startswith("#"):
        try:
            return int(value[1:])
        except ValueError:
            return None
    return None


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return deterministic validation errors for a reconciliation manifest."""
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    if _issue_number(manifest.get("epic_issue")) != EXPECTED_EPIC:
        errors.append(f"manifest epic_issue must be #{EXPECTED_EPIC}")

    rows = manifest.get("relations")
    if not isinstance(rows, list):
        return errors + ["manifest relations must be a list"]

    seen: Counter[int] = Counter()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"relation {index + 1} must be a mapping")
            continue
        issue = _issue_number(row.get("issue"))
        if issue is None:
            errors.append(f"relation {index + 1} has an invalid issue number")
            continue
        seen[issue] += 1
        if issue not in EXPECTED_P0_ISSUES:
            errors.append(f"relation references unknown P0 issue #{issue}")
        relation = row.get("relation")
        if relation not in VALID_RELATIONS:
            errors.append(
                f"P0 issue #{issue} has invalid relation {relation!r}; "
                f"expected one of {sorted(VALID_RELATIONS)}"
            )
        targets = row.get("native_targets")
        if not isinstance(targets, list) or not targets:
            errors.append(f"P0 issue #{issue} must name at least one native target")
        else:
            for target in targets:
                target_number = _issue_number(target)
                if target_number not in NATIVE_ISSUES:
                    errors.append(
                        f"P0 issue #{issue} references invalid native target {target!r}"
                    )
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            errors.append(f"P0 issue #{issue} must include a rationale")

    for issue in EXPECTED_P0_ISSUES:
        if seen[issue] == 0:
            errors.append(f"missing relation for P0 issue #{issue}")
        elif seen[issue] > 1:
            errors.append(f"duplicate relation for P0 issue #{issue}")
    return errors


def _canonical_body_block(manifest: dict[str, Any]) -> str:
    rows = {_issue_number(row["issue"]): row for row in manifest["relations"]}
    lines = [START_MARKER, "<!-- Generated from native-p0-reconciliation.yaml. -->"]
    for issue in EXPECTED_P0_ISSUES:
        row = rows[issue]
        targets = ", ".join(f"#{target}" for target in row["native_targets"])
        lines.append(f"- #{issue}: {row['relation']} -> {targets}")
    lines.append(END_MARKER)
    return "\n".join(lines)


def check_body_snapshot(manifest: dict[str, Any], body: str) -> list[str]:
    """Compare the canonical relation block with an issue-body snapshot."""
    expected = _canonical_body_block(manifest)
    start = body.find(START_MARKER)
    end = body.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        return ["epic body is missing the native-p0-reconciliation markers"]
    actual = body[start : end + len(END_MARKER)].strip()
    if actual != expected:
        return ["epic body relation block diverges from manifest"]
    return []


def fetch_github_issue(
    repo: str, issue: int, api_url: str = "https://api.github.com"
) -> dict[str, Any]:
    """Read one GitHub issue; this function never mutates GitHub state."""
    request = Request(
        f"{api_url.rstrip('/')}/repos/{repo}/issues/{issue}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "simplicio-program-graph",
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - URL is explicit CLI input
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("GitHub issue response must be an object")
    return value


def check_github(repo: str, manifest: dict[str, Any], api_url: str) -> list[str]:
    """Check the live epic/P0 bodies when explicitly requested."""
    errors: list[str] = []
    try:
        epic = fetch_github_issue(repo, EXPECTED_EPIC, api_url)
        errors.extend(check_body_snapshot(manifest, epic.get("body") or ""))
        for issue in EXPECTED_P0_ISSUES:
            item = fetch_github_issue(repo, issue, api_url)
            if item.get("state") == "open" and issue not in {
                int(row["issue"]) for row in manifest["relations"]
            }:
                errors.append(f"open P0 issue #{issue} has no manifest relation")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        errors.append(f"UNVERIFIED| GitHub read-only check unavailable: {exc}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/architecture/native-p0-reconciliation.yaml"),
    )
    parser.add_argument(
        "--epic-body",
        type=Path,
        default=Path("docs/architecture/native-p0-epic-314-body.md"),
    )
    parser.add_argument(
        "--github-repo", help="owner/repo for an explicit read-only API check"
    )
    parser.add_argument("--github-api", default="https://api.github.com")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"manifest error: {exc}")
        return 1
    errors = validate_manifest(manifest)
    if not errors:
        if args.epic_body.exists():
            errors.extend(
                check_body_snapshot(
                    manifest, args.epic_body.read_text(encoding="utf-8")
                )
            )
        else:
            errors.append(f"epic body snapshot not found: {args.epic_body}")
    if args.github_repo:
        errors.extend(check_github(args.github_repo, manifest, args.github_api))
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Program graph OK: {len(EXPECTED_P0_ISSUES)} P0 relations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
