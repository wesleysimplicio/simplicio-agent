#!/usr/bin/env python3
"""Deterministic audit for public docs/examples branding and claim hygiene.

This scanner is intentionally bounded: it audits line-oriented public-facing
text for four explicit concerns only:

- legacy Hermes branding leakage outside migration/credit contexts
- legacy ``hermes`` / ``hermes-agent`` command examples outside migration docs
- unsupported capability claims from a curated denylist of phrases
- canonical ``simplicio-agent`` command guidance in public examples

The migration/credit allowlists are explicit and path-aware. They do not act as
global suppressions: a line is skipped only when the matched path and line text
fit a reviewed allowlist rule.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".py",
    ".ps1",
    ".rst",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}

LEGACY_COMMAND = re.compile(
    r"\b(?:hermes-agent|hermes)\s+"
    r"(?:doctor|setup|update|chat|gateway|mcp|tools|daemon|skills|plugins|dash|serve|cron|auth|model|curator)\b",
    re.IGNORECASE,
)
LEGACY_BRAND = re.compile(r"\b(?:Hermes(?:\s+Turbo)?(?:\s+Agent)?|hermes-agent)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AllowlistEntry:
    name: str
    path_glob: str
    pattern: re.Pattern[str]
    klass: str
    reason: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str
    pattern: re.Pattern[str]
    message: str
    suggestion: str


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int
    column: int
    rule_id: str
    severity: str
    message: str
    evidence: str
    suggestion: str
    match_text: str


@dataclass(frozen=True)
class AllowlistedLine:
    path: str
    line: int
    klass: str
    allowlist: str
    reason: str
    evidence: str


DEFAULT_ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry(
        name="migration-alias-doc",
        path_glob="*",
        pattern=re.compile(
            r"\bdeprecated alias\b|\bdeprecated aliases\b|\btransition meta-package\b|"
            r"\bcanonical command\b|\buse\s+`?simplicio-agent\b",
            re.IGNORECASE,
        ),
        klass="migration",
        reason="reviewed migration guidance may cite legacy Hermes names verbatim",
    ),
    AllowlistEntry(
        name="credit-upstream-doc",
        path_glob="*",
        pattern=re.compile(
            r"\bcredit:\b|NousResearch/hermes-agent|original hermes-agent|"
            r"\bderived from Hermes Turbo Agent\b",
            re.IGNORECASE,
        ),
        klass="credit",
        reason="reviewed upstream credit may cite the legacy project name verbatim",
    ),
)

UNSUPPORTED_CLAIM_RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="unsupported-claim-every-platform",
        severity="error",
        pattern=re.compile(r"\bworks on every platform\b", re.IGNORECASE),
        message="unsupported capability claim: 'works on every platform'",
        suggestion="replace with a scoped, verified platform list or cite measured evidence",
    ),
    Rule(
        rule_id="unsupported-claim-every-mcp",
        severity="error",
        pattern=re.compile(r"\bsupports every MCP server\b", re.IGNORECASE),
        message="unsupported capability claim: 'supports every MCP server'",
        suggestion="replace with the specific supported MCP transport or integration contract",
    ),
    Rule(
        rule_id="unsupported-claim-local-llm-bundled",
        severity="error",
        pattern=re.compile(r"\bbundles a local LLM by default\b", re.IGNORECASE),
        message="unsupported capability claim: 'bundles a local LLM by default'",
        suggestion="describe the real optional local-model path instead of claiming a bundled default",
    ),
)


def iter_public_text_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in TEXT_EXTENSIONS else []
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS
    ]
    return sorted(files)


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def allowlist_match(rel_path: str, line: str) -> AllowlistEntry | None:
    for entry in DEFAULT_ALLOWLIST:
        if fnmatch.fnmatch(rel_path, entry.path_glob) and entry.pattern.search(line):
            return entry
    return None


def make_legacy_command_evidence(rel_path: str, line_no: int, line: str, match: re.Match[str]) -> Evidence:
    command = match.group(0)
    suggestion = re.sub(r"^(hermes-agent|hermes)\b", "simplicio-agent", command, flags=re.IGNORECASE)
    return Evidence(
        path=rel_path,
        line=line_no,
        column=match.start() + 1,
        rule_id="legacy-command",
        severity="error",
        message="legacy public command example uses a deprecated Hermes command",
        evidence=line.strip(),
        suggestion=suggestion,
        match_text=command,
    )


def make_legacy_brand_evidence(rel_path: str, line_no: int, line: str, match: re.Match[str]) -> Evidence:
    text = match.group(0)
    suggestion = "Simplicio Agent" if "agent" in text.lower() else "Simplicio"
    return Evidence(
        path=rel_path,
        line=line_no,
        column=match.start() + 1,
        rule_id="legacy-brand",
        severity="error",
        message="legacy Hermes branding leaked into a public doc/example",
        evidence=line.strip(),
        suggestion=suggestion,
        match_text=text,
    )


def make_rule_evidence(
    rel_path: str,
    line_no: int,
    line: str,
    rule: Rule,
    match: re.Match[str],
) -> Evidence:
    return Evidence(
        path=rel_path,
        line=line_no,
        column=match.start() + 1,
        rule_id=rule.rule_id,
        severity=rule.severity,
        message=rule.message,
        evidence=line.strip(),
        suggestion=rule.suggestion,
        match_text=match.group(0),
    )


def scan(root: Path) -> tuple[list[Evidence], list[AllowlistedLine], int]:
    findings: list[Evidence] = []
    allowlisted: list[AllowlistedLine] = []
    audited_files = 0

    for path in iter_public_text_files(root):
        audited_files += 1
        rel_path = relative_path(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            allowlist = allowlist_match(rel_path, line)
            if allowlist and (LEGACY_COMMAND.search(line) or LEGACY_BRAND.search(line)):
                allowlisted.append(AllowlistedLine(
                    path=rel_path,
                    line=line_no,
                    klass=allowlist.klass,
                    allowlist=allowlist.name,
                    reason=allowlist.reason,
                    evidence=line.strip(),
                ))
            else:
                legacy_command_match = LEGACY_COMMAND.search(line)
                if legacy_command_match:
                    findings.append(
                        make_legacy_command_evidence(rel_path, line_no, line, legacy_command_match)
                    )
                    continue

                legacy_brand_match = LEGACY_BRAND.search(line)
                if legacy_brand_match:
                    findings.append(
                        make_legacy_brand_evidence(rel_path, line_no, line, legacy_brand_match)
                    )
                    continue

            for rule in UNSUPPORTED_CLAIM_RULES:
                match = rule.pattern.search(line)
                if match:
                    findings.append(make_rule_evidence(rel_path, line_no, line, rule, match))
                    break

    findings.sort(key=lambda item: (item.path, item.line, item.column, item.rule_id))
    allowlisted.sort(key=lambda item: (item.path, item.line, item.allowlist))
    return findings, allowlisted, audited_files


def to_report(findings: list[Evidence], allowlisted: list[AllowlistedLine], audited_files: int) -> dict:
    by_rule = Counter(item.rule_id for item in findings)
    by_severity = Counter(item.severity for item in findings)
    allowlisted_by_class = Counter(item.klass for item in allowlisted)
    return {
        "schema": "simplicio.public-docs-audit/v1",
        "audited_files": audited_files,
        "finding_count": len(findings),
        "allowlisted_count": len(allowlisted),
        "by_rule": dict(sorted(by_rule.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "allowlisted_by_class": dict(sorted(allowlisted_by_class.items())),
        "findings": [
            {
                "path": item.path,
                "line": item.line,
                "column": item.column,
                "rule_id": item.rule_id,
                "severity": item.severity,
                "message": item.message,
                "evidence": item.evidence,
                "suggestion": item.suggestion,
                "match_text": item.match_text,
            }
            for item in findings
        ],
        "allowlisted": [
            {
                "path": item.path,
                "line": item.line,
                "class": item.klass,
                "allowlist": item.allowlist,
                "reason": item.reason,
                "evidence": item.evidence,
            }
            for item in allowlisted
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("docs"))
    parser.add_argument("--json", action="store_true", help="emit a machine-readable JSON report")
    args = parser.parse_args(argv)

    findings, allowlisted, audited_files = scan(args.root)
    report = to_report(findings, allowlisted, audited_files)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in findings:
            print(
                f"{item.path}:{item.line}:{item.column}: [{item.rule_id}] "
                f"{item.message} :: {item.evidence}"
            )
        print(
            f"public-docs-audit: {report['finding_count']} finding(s), "
            f"{report['allowlisted_count']} allowlisted line(s), "
            f"{report['audited_files']} file(s) audited"
        )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
