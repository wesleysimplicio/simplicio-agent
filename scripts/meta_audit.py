"""Generate a reproducible inventory report for all repository issues."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ARTIFACT_SCHEMA = "simplicio-agent.meta-audit-inventory/v2"
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "docs" / "audits" / "meta-audit-inventory.json"
REQUIRED_ISSUE_FIELDS = (
    "number",
    "title",
    "state",
    "created_at",
    "updated_at",
    "labels",
    "url",
    "dependencies",
    "evidence_status",
)
EVIDENCE_STATUSES = ("blocked", "unverified", "verified")


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
                "dependencies": sorted(
                    {
                        int(reference)
                        for reference in issue.get("dependencies", issue.get("dependency_references", []))
                    }
                ),
                "evidence_status": str(issue.get("evidence_status", "unverified")).lower(),
            }
        )
    return sorted(normalized, key=lambda item: (item["created_at"], item["number"]))


def build_artifact(repo: str, issues: list[dict[str, Any]], source: str) -> dict[str, Any]:
    states = Counter(issue["state"] for issue in issues)
    evidence = Counter(issue["evidence_status"] for issue in issues)
    issue_numbers = {issue["number"] for issue in issues}
    invalid_dependencies = sorted(
        {
            reference
            for issue in issues
            for reference in issue["dependencies"]
            if reference not in issue_numbers or reference == issue["number"]
        }
    )
    return {
        "schema": ARTIFACT_SCHEMA,
        "repository": repo,
        "source": source,
        "coverage": "issue_api_snapshot",
        "issues": issues,
        "summary": {
            "total": len(issues),
            "by_state": {state: states.get(state, 0) for state in ("open", "closed")},
            "open_issue_count": states.get("open", 0),
        },
        "audit": {
            "status": "incomplete",
            "required_fields": list(REQUIRED_ISSUE_FIELDS),
            "dependency_references": {
                "checked": True,
                "total": sum(len(issue["dependencies"]) for issue in issues),
                "invalid": invalid_dependencies,
            },
            "evidence": {
                "by_status": {status: evidence.get(status, 0) for status in EVIDENCE_STATUSES},
                "complete": evidence.get("unverified", 0) == 0 and evidence.get("blocked", 0) == 0,
            },
            "open_issue_count": states.get("open", 0),
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
    required = set(REQUIRED_ISSUE_FIELDS)
    numbers: list[int] = []
    dependency_total = 0
    evidence = Counter()
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
        if not isinstance(issue.get("dependencies"), list) or issue.get("dependencies") != sorted(issue.get("dependencies", [])):
            errors.append(f"issues[{index}].dependencies must be a sorted list")
        elif any(
            not isinstance(reference, int) or isinstance(reference, bool) or reference < 1
            for reference in issue["dependencies"]
        ):
            errors.append(f"issues[{index}].dependencies must contain positive integers")
        else:
            dependency_total += len(issue["dependencies"])
        if issue.get("evidence_status") not in EVIDENCE_STATUSES:
            errors.append(f"issues[{index}].evidence_status must be one of {', '.join(EVIDENCE_STATUSES)}")
        else:
            evidence[issue["evidence_status"]] += 1
    if len(numbers) != len(set(numbers)):
        errors.append("issue numbers must be unique")
    issue_numbers = set(numbers)
    invalid_dependencies = sorted(
        {
            reference
            for issue in issues
            if isinstance(issue, dict) and isinstance(issue.get("dependencies"), list)
            for reference in issue["dependencies"]
            if isinstance(reference, int) and (reference not in issue_numbers or reference == issue.get("number"))
        }
    )
    if invalid_dependencies:
        errors.append(f"dependency references must target another inventoried issue: {invalid_dependencies}")
    if issues != sorted(issues, key=lambda item: (item.get("created_at", ""), item.get("number", 0))):
        errors.append("issues must be sorted by created_at and number")
    states = Counter(issue.get("state") for issue in issues if isinstance(issue, dict))
    expected = {
        "total": len(issues),
        "by_state": {state: states.get(state, 0) for state in ("open", "closed")},
        "open_issue_count": states.get("open", 0),
    }
    if artifact.get("summary") != expected:
        errors.append(f"summary must equal {json.dumps(expected, sort_keys=True)}")
    audit = artifact.get("audit")
    if not isinstance(audit, dict):
        errors.append("audit must be an object")
    else:
        if audit.get("status") not in {"complete", "incomplete"}:
            errors.append("audit.status must be complete or incomplete")
        if audit.get("required_fields") != list(REQUIRED_ISSUE_FIELDS):
            errors.append(f"audit.required_fields must equal {json.dumps(list(REQUIRED_ISSUE_FIELDS))}")
        dependencies = audit.get("dependency_references")
        expected_dependencies = {"checked": True, "total": dependency_total, "invalid": invalid_dependencies}
        if dependencies != expected_dependencies:
            errors.append(
                "audit.dependency_references must equal " + json.dumps(expected_dependencies, sort_keys=True)
            )
        expected_evidence = {
            "by_status": {status: evidence.get(status, 0) for status in EVIDENCE_STATUSES},
            "complete": evidence.get("unverified", 0) == 0 and evidence.get("blocked", 0) == 0,
        }
        if audit.get("evidence") != expected_evidence:
            errors.append("audit.evidence must match issue evidence statuses")
        if audit.get("open_issue_count") != states.get("open", 0):
            errors.append("audit.open_issue_count must match open issue states")
        if audit.get("status") == "complete" and not expected_evidence["complete"]:
            errors.append("audit.status cannot be complete while evidence is unverified or blocked")
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
        f"- Audit status: **incomplete**",
        f"- Evidence status: **unverified by default**",
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


def render_json(repo: str, issues: list[dict[str, Any]], source: str) -> str:
    """Render the same report as stable, human-readable JSON."""
    return json.dumps(build_artifact(repo, issues, source), indent=2, ensure_ascii=False) + "\n"


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
    parser.add_argument("--json", action="store_true", help="Emit validator results or the report as JSON")
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
    report = render_json(args.repo, issues, source) if args.json else render_report(args.repo, issues, source)
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
