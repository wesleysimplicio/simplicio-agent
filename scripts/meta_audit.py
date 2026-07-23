"""Generate a reproducible inventory report for all repository issues."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


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
                "labels": [name for name in names if name],
                "url": str(issue.get("html_url", issue.get("url", ""))),
            }
        )
    return sorted(normalized, key=lambda item: (item["created_at"], item["number"]))


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
    parser.add_argument("--repo", required=True, help="GitHub owner/name")
    parser.add_argument("--input", type=Path, help="Saved JSON response for offline reproduction")
    parser.add_argument("--output", type=Path, help="Markdown output path; stdout when omitted")
    args = parser.parse_args(argv)
    payload, source = load_payload(args.input, args.repo)
    report = render_report(args.repo, normalize_issues(payload), source)
    if args.output:
        args.output.write_text(report, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
