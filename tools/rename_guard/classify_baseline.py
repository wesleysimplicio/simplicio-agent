#!/usr/bin/env python3
"""Classify frozen source occurrences for the issue #187 inventory.

The normal scanner deliberately keeps ``baseline`` as an operational
regression state.  This companion step assigns every baseline occurrence a
reviewable taxonomy class, reason, owner and downstream issue without
renaming source or silently extending the baseline.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from collections import Counter
from pathlib import Path

DEFAULT_OUTPUT = Path("tools/rename_guard/baseline-classification.json")
OWNER = "wesley.simplicio@evtit.com"

# First match wins.  Rules are path-scoped so an occurrence cannot be hidden
# by a permissive repository-wide expression.
RULES: list[tuple[str, str, str, str]] = [
    ("*/dist/*", "GENERATED_REBUILD", "build output; regenerate from source", "#188"),
    ("tests/*", "historical-fixture", "backward-compatibility fixture or assertion", "#193"),
    ("archive/*", "KEEP_UPSTREAM_REFERENCE", "frozen pre-fork upstream source, not shipped", "#193"),
    ("CHANGELOG.md", "KEEP_UPSTREAM_REFERENCE", "historical upstream attribution", "#193"),
    ("hermes_cli/*", "compatibility-temporary", "internal module namespace pending namespace migration", "#190"),
    ("hermes_constants.py", "compatibility-temporary", "HERMES_* cross-repository runtime contract", "#193"),
    ("hermes_logging.py", "compatibility-temporary", "internal module pending namespace migration", "#190"),
    ("hermes_state.py", "compatibility-temporary", "internal module pending namespace migration", "#190"),
    ("hermes_time.py", "compatibility-temporary", "internal module pending namespace migration", "#190"),
    ("hermes_bootstrap.py", "compatibility-temporary", "internal bootstrap module pending namespace migration", "#190"),
    ("hermes_cli.spec", "compatibility-temporary", "PyInstaller spec references internal module name", "#190"),
    ("gateway/*", "compatibility-temporary", "internal implementation and HERMES_* contract", "#190"),
    ("tools/*", "compatibility-temporary", "internal implementation and HERMES_* contract", "#190"),
    ("agent/*", "compatibility-temporary", "internal implementation and HERMES_* contract", "#190"),
    ("tui_gateway/*", "compatibility-temporary", "internal implementation and HERMES_* contract", "#190"),
    ("acp_adapter/*", "compatibility-temporary", "internal adapter implementation", "#190"),
    ("cron/*", "compatibility-temporary", "internal scheduler and legacy state path", "#117"),
    ("scripts/*", "compatibility-temporary", "developer-only internal script", "#190"),
    ("rust_ext/*", "compatibility-temporary", "internal extension namespace", "#190"),
    ("providers/*", "compatibility-temporary", "internal provider implementation", "#190"),
    ("model_tools.py", "compatibility-temporary", "internal module import", "#190"),
    ("mcp_serve.py", "compatibility-temporary", "internal module import", "#190"),
    ("run_agent.py", "compatibility-temporary", "internal module import", "#190"),
    ("batch_runner.py", "compatibility-temporary", "internal module import", "#190"),
    ("trajectory_compressor.py", "compatibility-temporary", "internal module import", "#190"),
    ("mini_swe_runner.py", "compatibility-temporary", "internal module import", "#190"),
    ("toolsets.py", "compatibility-temporary", "internal helper identifier", "#190"),
    ("utils.py", "compatibility-temporary", "internal helper identifier", "#190"),
    ("hooks/*", "compatibility-temporary", "internal hook and environment contract", "#190"),
    ("acp_registry/*", "compatibility-temporary", "internal registry contract", "#190"),
    (".env.example", "MIGRATE_STATE", "legacy HERMES_* environment aliases", "#117"),
    (".envrc", "MIGRATE_STATE", "legacy HERMES_* environment aliases", "#117"),
    ("nix/*", "public-must-migrate", "Nix package identity ships the old brand", "#118"),
    ("packaging/*", "public-must-migrate", "packaging metadata ships the old brand", "#118"),
    ("docker/*", "public-must-migrate", "Docker distribution identity ships the old brand", "#118"),
    ("Dockerfile", "public-must-migrate", "image build ships old-brand labels or paths", "#118"),
    ("docker-compose*.yml", "public-must-migrate", "compose service identity ships the old brand", "#118"),
    (".dockerignore", "public-must-migrate", "old-brand container path layout", "#118"),
    (".hadolint.yaml", "public-must-migrate", "Dockerfile lint contract", "#118"),
    ("pyproject.toml", "public-must-migrate", "PyPI package or entry-point identity", "#118"),
    ("setup.py", "public-must-migrate", "package build metadata", "#118"),
    ("MANIFEST.in", "public-must-migrate", "package manifest path", "#118"),
    ("package.json", "public-must-migrate", "npm package identity", "#118"),
    ("flake.nix", "public-must-migrate", "Nix flake package identity", "#118"),
    ("constraints-termux.txt", "public-must-migrate", "Termux package identity", "#118"),
    ("setup-hermes.sh", "public-must-migrate", "user-facing installer identity", "#118"),
    ("cli-config.yaml.example", "public-must-migrate", "user-facing example configuration", "#188"),
    ("cli.py", "public-must-migrate", "CLI banner or help identity", "#188"),
    ("ui-tui/*", "public-must-migrate", "TUI package or UI identity", "#188"),
    ("apps/*", "public-must-migrate", "installer application identity", "#188"),
    ("desktop/*", "public-must-migrate", "Desktop public surface mixed with internal integration", "#188"),
    ("optional-skills/*", "public-must-migrate", "distributed skill metadata or docs", "#189"),
    ("skills/*", "public-must-migrate", "distributed skill metadata or docs", "#189"),
    ("plugins/*", "public-must-migrate", "distributed plugin identity or integration", "#189"),
    ("locales/*", "public-must-migrate", "translated product message catalog", "#192"),
    ("docs/*", "public-must-migrate", "public documentation surface", "#189"),
    ("AGENTS.md", "public-must-migrate", "public contributor and agent documentation", "#189"),
    ("README*.md", "public-must-migrate", "public README surface", "#189"),
    ("CONTRIBUTING*.md", "public-must-migrate", "public contributor documentation", "#189"),
    ("SECURITY*.md", "public-must-migrate", "public security documentation", "#189"),
    ("datagen-config-examples/*", "public-must-migrate", "distributed example configuration", "#189"),
    ("optional-mcps/*", "public-must-migrate", "distributed MCP configuration", "#191"),
    (".github/*", "compatibility-temporary", "CI and workflow internals", "#194"),
    (".gitignore", "KEEP_INTERNAL", "repository-local internal path contract", "#190"),
    (".plans/*", "historical-fixture", "internal planning note, not shipped", "#193"),
    ("simplicio-agent", "public-must-migrate", "installed CLI launcher identity", "#188"),
    ("hermes", "compatibility-temporary", "legacy command symlink kept during deprecation", "#193"),
]


def classify(path: str) -> tuple[str, str, str]:
    for path_glob, classification, reason, issue in RULES:
        if fnmatch.fnmatch(path, path_glob):
            return classification, reason, issue
    return "error", "no path rule matched; manual classification required", "#187"


def build_manifest(report: dict) -> dict:
    baseline = [o for o in report["occurrences"] if o["class"] == "baseline"]
    files = sorted({o["path"] for o in baseline})
    file_data = {path: classify(path) for path in files}
    by_class = Counter(file_data[o["path"]][0] for o in baseline)
    by_file_class = Counter(value[0] for value in file_data.values())
    by_issue = Counter(file_data[o["path"]][2] for o in baseline)
    return {
        "schema": "simplicio.rename-inventory/v1",
        "generated_from": "tools/rename_guard/scanner.py baseline occurrences",
        "granularity": "file",
        "total_occurrences": len(baseline),
        "total_files": len(files),
        "unclassified_occurrences": by_class.get("error", 0),
        "by_class": dict(sorted(by_class.items())),
        "by_class_files": dict(sorted(by_file_class.items())),
        "by_owning_issue": dict(sorted(by_issue.items())),
        "files": [
            {"path": path, "class": file_data[path][0], "reason": file_data[path][1],
             "owner": OWNER, "owning_issue": file_data[path][2]}
            for path in files
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    manifest = build_manifest(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"classified {manifest['total_occurrences']} baseline occurrences across "
          f"{manifest['total_files']} files; unclassified={manifest['unclassified_occurrences']}")
    return 0 if manifest["unclassified_occurrences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
