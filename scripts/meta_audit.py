"""Generate a reproducible inventory report for all repository issues."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ARTIFACT_SCHEMA = "simplicio-agent.meta-audit-inventory/v1"
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "docs" / "audits" / "meta-audit-inventory.json"


def _pages(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield issue objects from gh --paginate --slurp or a single page."""
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
            elif isinstance(item, list):
                yield from _pages(item)


def normalize_issues(payload: Any) -> list[dict[str, Any]]:
    """Normalize API objects, exclude pull requests, and sort deterministically."""
    normalized = []
    for issue in _pages(payload):
        if issue.get("pull_request") is not None:
            continue
        labels = issue.get("labels", [])
        names = sorted(
            str(label.get("name", "")) if isinstance(label, dict) else str(label)
            for label in labels
        )
        normalized.append(
            {
                "number": int(issue["number"]),
                "title": str(issue.get("title", "")).strip(),
                "state": str(issue.get("state", "unknown")).lower(),
                "created_at": str(issue.get("created_at", "")),
                "updated_at": str(issue.get("updated_at", "")),
                "labels": [name for name in names if name],
                "url": str(issue.get("html_url", issue.get("url", ""))),
            }
        )
    return sorted(normalized, key=lambda item: (item["created_at"], item["number"]))


def build_artifact(repo: str, issues: list[dict[str, Any]], source: str) -> dict[str, Any]:
    states = Counter(issue["state"] for issue in issues)
    return {
        "schema": ARTIFACT_SCHEMA,
        "repository": repo,
        "source": source,
        "coverage": "issue_api_snapshot",
        "issues": issues,
        "summary": {
            "total": len(issues),
            "by_state": {state: states.get(state, 0) for state in ("open", "closed")},
        },
    }


def validate_artifact(artifact: Any) -> list[str]:
    """Return deterministic contract violations for a checked-in snapshot."""
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return ["artifact root must be an object"]
    if artifact.get("schema") != ARTIFACT_SCHEMA:
        errors.append(f"schema must be {ARTIFACT_SCHEMA!r}")
    if not isinstance(artifact.get("repository"), str) or not artifact["repository"].strip():
        errors.append("repository must be a non-empty string")
    if artifact.get("coverage") != "issue_api_snapshot":
        errors.append("coverage must be 'issue_api_snapshot'")
    issues = artifact.get("issues")
    if not isinstance(issues, list):
        return errors + ["issues must be a list"]
    required = {"number", "title", "state", "created_at", "updated_at", "labels", "url"}
    numbers: list[int] = []
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            errors.append(f"issues[{index}] must be an object")
            continue
        missing = required - issue.keys()
        if missing:
            errors.append(f"issues[{index}] missing: {', '.join(sorted(missing))}")
        if not isinstance(issue.get("number"), int) or isinstance(issue.get("number"), bool) or issue["number"] < 1:
            errors.append(f"issues[{index}].number must be a positive integer")
        else:
            numbers.append(issue["number"])
        if issue.get("state") not in {"open", "closed"}:
            errors.append(f"issues[{index}].state must be open or closed")
        if not isinstance(issue.get("labels"), list) or issue.get("labels") != sorted(issue.get("labels", [])):
            errors.append(f"issues[{index}].labels must be a sorted list")
    if len(numbers) != len(set(numbers)):
        errors.append("issue numbers must be unique")
    if issues != sorted(issues, key=lambda item: (item.get("created_at", ""), item.get("number", 0))):
        errors.append("issues must be sorted by created_at and number")
    states = Counter(issue.get("state") for issue in issues if isinstance(issue, dict))
    expected = {"total": len(issues), "by_state": {state: states.get(state, 0) for state in ("open", "closed")}}
    if artifact.get("summary") != expected:
        errors.append(f"summary must equal {json.dumps(expected, sort_keys=True)}")
    return errors


def render_report(repo: str, issues: list[dict[str, Any]], source: str) -> str:
    """Render a stable Markdown report without generation-time values."""
    states = Counter(issue["state"] for issue in issues)
    lines = [
        "# Meta-audit issue inventory",
        "",
        f"Repository: `{repo}`",
        f"Source: `{source}`",
        "",
        "## Counts",
        "",
        f"- Total issues: **{len(issues)}**",
        f"- Open: **{states.get('open', 0)}**",
        f"- Closed: **{states.get('closed', 0)}**",
        "",
        "## Inventory",
        "",
        "| Number | State | Created | Labels | Title | URL |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for issue in issues:
        labels = ", ".join(issue["labels"]) or "-"
        values = [
            str(issue["number"]),
            issue["state"],
            issue["created_at"],
            labels,
            issue["title"],
            issue["url"],
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines) + "\n"


def load_payload(path: Path | None, repo: str) -> tuple[Any, str]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8")), f"snapshot:{path.name}"
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues?state=all&per_page=100"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout), "gh api --paginate"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="GitHub owner/name")
    parser.add_argument("--input", type=Path, help="Saved JSON response for offline reproduction")
    parser.add_argument("--output", type=Path, help="Markdown output path; stdout when omitted")
    parser.add_argument("--artifact", type=Path, help="Write a checked-in JSON inventory snapshot")
    parser.add_argument("--validate", action="store_true", help="Validate a checked-in JSON inventory snapshot")
    parser.add_argument("--json", action="store_true", help="Emit validator results as JSON")
    args = parser.parse_args(argv)
    if args.validate:
        artifact_path = args.artifact or DEFAULT_ARTIFACT
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            errors = validate_artifact(artifact)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [str(exc)]
        payload = {"valid": not errors, "errors": errors, "path": str(artifact_path)}
        print(json.dumps(payload, sort_keys=True) if args.json else ("valid\n" if not errors else "\n".join(errors)))
        return 0 if not errors else 1
    if not args.repo:
        parser.error("--repo is required unless --validate is used")
    payload, source = load_payload(args.input, args.repo)
    issues = normalize_issues(payload)
    report = render_report(args.repo, issues, source)
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(build_artifact(args.repo, issues, source), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.output:
        args.output.write_text(report, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
