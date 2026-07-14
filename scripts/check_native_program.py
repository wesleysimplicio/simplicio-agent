"""Validate the bounded parent gate for Native epic #314.

This gate is intentionally read-only.  The checked-in manifest records the
child-to-ADR/artifact contract, while the existing P0 reconciliation graph is
the source of truth for reverse program coverage.  Optional GitHub checks use
an injected fetcher, so callers can supply a mock without permitting writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

import yaml

try:
    from scripts import check_program_graph
except ImportError:  # Running this file directly puts ``scripts`` on sys.path.
    import check_program_graph  # type: ignore[no-redef]

EXPECTED_EPIC = 314
EXPECTED_CHILDREN = tuple(range(315, 324))
MANIFEST_SCHEMA = 1
EVIDENCE_FIELDS = ("live_process", "release_artifact", "rollback")
EVIDENCE_PREFIXES = ("MEASURED|", "UNVERIFIED|")


class DuplicateKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate keys instead of dropping one."""


def _construct_mapping(
    loader: DuplicateKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
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
    with path.open(encoding="utf-8") as stream:
        value = yaml.load(stream, Loader=DuplicateKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("native program manifest root must be a mapping")
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


def _as_paths(value: Any, field: str, errors: list[str], issue: int) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        errors.append(f"child #{issue} must declare non-empty {field} paths")
        return []
    return value


def _reverse_program_graph(graph: dict[str, Any]) -> dict[int, list[int]]:
    reverse: defaultdict[int, list[int]] = defaultdict(list)
    for row in graph.get("relations", []):
        if not isinstance(row, dict):
            continue
        source = _issue_number(row.get("issue"))
        for target in row.get("native_targets", []):
            target_number = _issue_number(target)
            if source is not None and target_number is not None:
                reverse[target_number].append(source)
    return {issue: sorted(set(sources)) for issue, sources in reverse.items()}


def validate_manifest(
    manifest: Mapping[str, Any], *, root: Path, graph_path: Path
) -> list[str]:
    """Return structural, artifact, and program-graph contract errors."""
    errors: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        errors.append(f"manifest schema_version must be {MANIFEST_SCHEMA}")
    if _issue_number(manifest.get("epic_issue")) != EXPECTED_EPIC:
        errors.append(f"manifest epic_issue must be #{EXPECTED_EPIC}")

    children = manifest.get("children")
    if not isinstance(children, list):
        return errors + ["manifest children must be a list"]

    seen: dict[int, int] = defaultdict(int)
    declared_graph: dict[int, list[int]] = {}
    for index, child in enumerate(children):
        if not isinstance(child, Mapping):
            errors.append(f"child {index + 1} must be a mapping")
            continue
        issue = _issue_number(child.get("issue"))
        if issue is None:
            errors.append(f"child {index + 1} has an invalid issue number")
            continue
        seen[issue] += 1
        if issue not in EXPECTED_CHILDREN:
            errors.append(f"manifest references unknown Native child #{issue}")
        if not isinstance(child.get("title"), str) or not child["title"].strip():
            errors.append(f"child #{issue} must declare a title")
        for path_field in ("adr", "implementation", "tests"):
            paths = _as_paths(child.get(path_field), path_field, errors, issue)
            if path_field == "adr" and not any(
                "ADR-0023-simplicio-native-inside-out.md" in path for path in paths
            ):
                errors.append(f"child #{issue} ADR coverage must cite ADR-0023")
            for relative in paths:
                if not (root / relative).is_file():
                    errors.append(
                        f"child #{issue} {path_field} path not found: {relative}"
                    )
        graph_targets = child.get("program_graph_p0")
        if not isinstance(graph_targets, list) or not all(
            _issue_number(target) in check_program_graph.EXPECTED_P0_ISSUES
            for target in graph_targets
        ):
            errors.append(
                f"child #{issue} must declare program_graph_p0 as a list of known P0 issues"
            )
        else:
            declared_graph[issue] = sorted(
                _issue_number(target) for target in graph_targets
            )

    for issue in EXPECTED_CHILDREN:
        if seen[issue] == 0:
            errors.append(f"missing Native child mapping for #{issue}")
        elif seen[issue] > 1:
            errors.append(f"duplicate Native child mapping for #{issue}")
    unknown = sorted(issue for issue in seen if issue not in EXPECTED_CHILDREN)
    if unknown:
        errors.append(f"unknown Native child mappings: {unknown}")

    evidence = manifest.get("evidence")
    if not isinstance(evidence, Mapping):
        errors.append("manifest evidence must be a mapping")
    else:
        for field in EVIDENCE_FIELDS:
            value = evidence.get(field)
            if not isinstance(value, str) or not value.startswith(EVIDENCE_PREFIXES):
                errors.append(
                    f"evidence.{field} must be explicitly tagged MEASURED| or UNVERIFIED|"
                )

    try:
        graph = check_program_graph.load_manifest(root / graph_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"program graph unavailable: {exc}")
    else:
        graph_errors = check_program_graph.validate_manifest(graph)
        errors.extend(f"program graph: {error}" for error in graph_errors)
        reverse = _reverse_program_graph(graph)
        for issue in EXPECTED_CHILDREN:
            if issue in declared_graph and declared_graph[issue] != reverse.get(
                issue, []
            ):
                errors.append(
                    f"child #{issue} program graph coverage diverges: "
                    f"declared {declared_graph[issue]}, actual {reverse.get(issue, [])}"
                )
        native_issues = {
            _issue_number(issue) for issue in graph.get("native_issues", [])
        }
        if native_issues != set(EXPECTED_CHILDREN):
            errors.append("program graph native_issues must cover exactly #315-#323")
    return errors


def readiness(manifest: Mapping[str, Any]) -> tuple[bool, list[str]]:
    evidence = manifest.get("evidence", {})
    statuses = [
        str(evidence.get(field, "UNVERIFIED| missing")) for field in EVIDENCE_FIELDS
    ]
    unverified = [status for status in statuses if status.startswith("UNVERIFIED|")]
    return not unverified, unverified


IssueFetcher = Callable[[int], Mapping[str, Any]]


def check_live_issues(
    manifest: Mapping[str, Any], fetch_issue: IssueFetcher
) -> list[str]:
    """Perform a read-only, dependency-injected check of child issue linkage."""
    errors: list[str] = []
    for child in manifest.get("children", []):
        if not isinstance(child, Mapping):
            continue
        issue = _issue_number(child.get("issue"))
        if issue is None:
            continue
        try:
            payload = fetch_issue(issue)
        except Exception as exc:  # noqa: BLE001 - API failures are unverified evidence.
            errors.append(
                f"UNVERIFIED| GitHub read-only check failed for #{issue}: {exc}"
            )
            continue
        if not isinstance(payload, Mapping):
            errors.append(f"child #{issue} API response is not an object")
            continue
        if _issue_number(payload.get("number")) != issue:
            errors.append(f"child #{issue} API response has mismatched number")
        if str(payload.get("title") or "") != str(child.get("title") or ""):
            errors.append(
                f"child #{issue} live title diverges from the parent manifest"
            )
        body = str(payload.get("body") or "")
        if "#314" not in body:
            errors.append(f"child #{issue} live body does not reference parent #314")
        if "ADR-0023" not in body:
            errors.append(f"child #{issue} live body does not reference ADR-0023")
    return errors


def fetch_github_issue(repo: str, issue: int, *, api_url: str) -> Mapping[str, Any]:
    request = Request(
        f"{api_url.rstrip('/')}/repos/{repo}/issues/{issue}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "simplicio-native-program-gate",
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - explicit CLI input.
        value = json.load(response)
    if not isinstance(value, Mapping):
        raise ValueError("GitHub issue response must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/architecture/native-program-gate.yaml"),
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("docs/architecture/native-p0-reconciliation.yaml"),
    )
    parser.add_argument(
        "--github-repo", help="owner/repo for an explicit read-only API check"
    )
    parser.add_argument("--github-api", default="https://api.github.com")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="fail while live/release evidence is UNVERIFIED",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    try:
        manifest = load_manifest(root / args.manifest)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"manifest error: {exc}")
        return 1
    errors = validate_manifest(manifest, root=root, graph_path=args.graph)
    if args.github_repo:
        errors.extend(
            check_live_issues(
                manifest,
                lambda issue: fetch_github_issue(
                    args.github_repo, issue, api_url=args.github_api
                ),
            )
        )
    if errors:
        print("\n".join(errors))
        return 1
    ready, pending = readiness(manifest)
    print(
        f"Native #314 parent gate contract OK: {len(EXPECTED_CHILDREN)} child mappings"
    )
    for status in pending:
        print(status)
    if args.require_ready and not ready:
        print("UNVERIFIED| Native #314 live/release completion gate is not ready")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
