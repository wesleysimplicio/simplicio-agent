"""Validate the read-only Wave 22 native supersede-sweep manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

EXPECTED_SWEEP_ISSUE = 346
VALID_VERDICTS = frozenset({"superseded", "subordinated", "independent"})
VALID_RECEIPT_STATUSES = frozenset({"VERIFIED", "UNVERIFIED"})


class DuplicateKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


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
    """Load a manifest without silently discarding duplicate keys."""
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


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_receipt(name: str, receipt: Any, errors: list[str]) -> None:
    if not isinstance(receipt, dict):
        errors.append(f"receipt {name} must be a mapping")
        return
    status = receipt.get("status")
    if status not in VALID_RECEIPT_STATUSES:
        errors.append(f"receipt {name} has invalid status {status!r}")
    if not _nonempty_string(receipt.get("evidence")):
        errors.append(f"receipt {name} must include evidence")


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return deterministic contract errors; never perform network or mutation."""
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    if manifest.get("contract") != "simplicio.backlog-supersede-sweep/v1":
        errors.append("manifest contract must be simplicio.backlog-supersede-sweep/v1")
    if _issue_number(manifest.get("sweep_issue")) != EXPECTED_SWEEP_ISSUE:
        errors.append(f"manifest sweep_issue must be #{EXPECTED_SWEEP_ISSUE}")
    if manifest.get("read_only") is not True:
        errors.append("manifest read_only must be true")

    scope = manifest.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("issue_numbers"), list):
        errors.append("manifest scope.issue_numbers must be a list")
        scoped: list[int] = []
    else:
        scoped = []
        for value in scope["issue_numbers"]:
            number = _issue_number(value)
            if number is None:
                errors.append(f"scope contains invalid issue number {value!r}")
            else:
                scoped.append(number)
        if len(set(scoped)) != len(scoped):
            errors.append("scope.issue_numbers must not contain duplicates")

    verdicts = manifest.get("verdicts")
    if (
        not isinstance(verdicts, list)
        or len(verdicts) != len(VALID_VERDICTS)
        or set(verdicts) != VALID_VERDICTS
    ):
        errors.append(f"manifest verdicts must contain {sorted(VALID_VERDICTS)!r}")

    criteria = manifest.get("acceptance_criteria")
    if not isinstance(criteria, dict) or not criteria:
        errors.append("manifest acceptance_criteria must be a non-empty mapping")
        criteria = {}
    elif any(not _nonempty_string(value) for value in criteria.values()):
        errors.append("every acceptance criterion must have a description")

    rows = manifest.get("issues")
    if not isinstance(rows, list):
        return errors + ["manifest issues must be a list"]

    seen: Counter[int] = Counter()
    mapped: Counter[str] = Counter()
    for index, row in enumerate(rows):
        label = f"issue row {index + 1}"
        if not isinstance(row, dict):
            errors.append(f"{label} must be a mapping")
            continue
        issue = _issue_number(row.get("issue"))
        if issue is None:
            errors.append(f"{label} has an invalid issue number")
            continue
        seen[issue] += 1
        if issue not in scoped:
            errors.append(f"{label} references out-of-scope issue #{issue}")
        verdict = row.get("verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"issue #{issue} has invalid verdict {verdict!r}")
        target_values = row.get("target_issues")
        if not isinstance(target_values, list):
            errors.append(f"issue #{issue} target_issues must be a list")
        else:
            targets = [_issue_number(value) for value in target_values]
            if any(target is None for target in targets):
                errors.append(f"issue #{issue} has an invalid target issue")
            if verdict == "independent" and target_values:
                errors.append(f"independent issue #{issue} must not have target issues")
            if verdict in {"superseded", "subordinated"} and not target_values:
                errors.append(f"{verdict} issue #{issue} must have target issues")
        if not _nonempty_string(row.get("rationale")):
            errors.append(f"issue #{issue} must include a rationale")
        ac_mapping = row.get("ac_mapping")
        if not isinstance(ac_mapping, list) or not ac_mapping:
            errors.append(f"issue #{issue} must map at least one acceptance criterion")
        else:
            for criterion in ac_mapping:
                if criterion not in criteria:
                    errors.append(
                        f"issue #{issue} maps unknown acceptance criterion {criterion!r}"
                    )
                elif isinstance(criterion, str):
                    mapped[criterion] += 1
        owner_window = row.get("owner_window")
        _validate_receipt(f"issue #{issue}.owner_window", owner_window, errors)
        if isinstance(owner_window, dict) and owner_window.get("window_hours") != 48:
            errors.append(f"issue #{issue} owner_window must be 48 hours")

    for issue in scoped:
        if seen[issue] == 0:
            errors.append(f"missing classification for issue #{issue}")
        elif seen[issue] > 1:
            errors.append(f"duplicate classification for issue #{issue}")
    for criterion in criteria:
        if mapped[criterion] == 0:
            errors.append(f"acceptance criterion {criterion} is not mapped")

    receipts = manifest.get("receipts")
    if not isinstance(receipts, dict):
        errors.append("manifest receipts must be a mapping")
    else:
        for name in ("anti_bulk_close", "live_api", "owner_window"):
            _validate_receipt(name, receipts.get(name), errors)
        anti_bulk = receipts.get("anti_bulk_close")
        if isinstance(anti_bulk, dict):
            if anti_bulk.get("mutation_allowed") is not False:
                errors.append("anti_bulk_close mutation_allowed must be false")
            if anti_bulk.get("close_operations") != 0:
                errors.append("anti_bulk_close close_operations must be zero")
            if anti_bulk.get("per_issue_review_required") is not True:
                errors.append("anti_bulk_close requires per_issue_review_required=true")
        owner = receipts.get("owner_window")
        if isinstance(owner, dict) and owner.get("window_hours") != 48:
            errors.append("top-level owner_window must be 48 hours")

    ledger = manifest.get("ledger")
    if not isinstance(ledger, dict):
        errors.append("manifest ledger must be a mapping")
    elif ledger.get("schema") != "simplicio.backlog-supersede-ledger/v1":
        errors.append("ledger schema is invalid")
    return errors


def fetch_github_issue(
    repo: str, issue: int, api_url: str = "https://api.github.com"
) -> dict[str, Any]:
    """Read one GitHub issue using GET only; this function cannot mutate GitHub."""
    request = Request(
        f"{api_url.rstrip('/')}/repos/{repo}/issues/{issue}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "simplicio-supersede-sweep",
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - explicit read-only URL
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("GitHub issue response must be an object")
    return value


def check_github(
    repo: str,
    manifest: dict[str, Any],
    api_url: str = "https://api.github.com",
    fetcher: Callable[[str, int, str], dict[str, Any]] = fetch_github_issue,
) -> list[str]:
    """Read issue state for a manifest scope; return violations or UNVERIFIED notes."""
    results: list[str] = []
    for value in manifest["scope"]["issue_numbers"]:
        issue = _issue_number(value)
        if issue is None:  # local validation reports the precise malformed value
            continue
        try:
            item = fetcher(repo, issue, api_url)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            results.append(
                f"UNVERIFIED| GitHub read-only check unavailable for #{issue}: {exc}"
            )
            continue
        if item.get("number") not in (None, issue):
            results.append(f"issue #{issue} API response has mismatched number")
        # The checker deliberately does not infer a verdict or perform a close.
        if not item.get("assignees"):
            results.append(f"UNVERIFIED| no live owner receipt for #{issue}")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/backlog/native-supersede-sweep-2026-07.yaml"),
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
    if args.github_repo and not errors:
        errors.extend(check_github(args.github_repo, manifest, args.github_api))
    if errors:
        print("\n".join(errors))
        return 1
    rows = len(manifest["issues"])
    print(f"Supersede sweep OK: {rows}/{rows} scoped classifications; read-only")
    if manifest["receipts"]["live_api"]["status"] == "UNVERIFIED":
        print("UNVERIFIED| live API, owner, and 48-hour evidence unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
