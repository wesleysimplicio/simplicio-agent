#!/usr/bin/env python3
"""Assign a #186 taxonomy class to every occurrence still carrying only the
operational ``baseline`` label from ``tools/rename_guard/scanner.py``.

This is the inventory-manifest deliverable for issue #187: every occurrence
gets a class, a reason and an owning downstream issue. It does not rename
anything and does not touch ``allowlist.json`` — ``public-must-migrate``
occurrences are real debt that must be fixed by a dedicated, tested PR on
their owning surface issue (#117/#118/#188-#193), not silently allowlisted
away. Classification is per-file (dominant content of the file), not
per-line, because per-line judgment calls at this volume (2,300+ files)
are not reviewable in one pass; the file-level grain is recorded in the
output schema so a future finer-grained pass can supersede it.
"""
from __future__ import annotations

import fnmatch
import json
from collections import Counter, defaultdict
from pathlib import Path

REPORT = Path("/tmp/rg_report.json")
OUT_JSON = Path("tools/rename_guard/baseline-classification.json")
OUT_MD = Path("docs/rename-inventory-status.md")

# (glob, class, reason, owner_issue) — first match wins.
RULES: list[tuple[str, str, str, str]] = [
    # Generated/build output — never hand-edited, regenerate from source.
    ("desktop/dist/*", "GENERATED_REBUILD",
     "compiled/minified Desktop bundle; regenerate from source, not editable", "#188"),
    ("*/dist/*", "GENERATED_REBUILD",
     "build output; regenerate from source, not editable", "#188"),

    # Historical/back-compat test fixtures — epic explicitly allows this class to stay.
    ("tests/*", "historical-fixture",
     "test fixtures/assertions intentionally exercise legacy identifiers, aliases and "
     "back-compat paths per epic #186 non-objetivos (\"testes de backward compatibility\")",
     "#193"),

    # Frozen pre-fork upstream source and credits (already covered by allowlist,
    # kept here too so the manifest is self-contained).
    ("archive/*", "KEEP_UPSTREAM_REFERENCE",
     "frozen pre-fork upstream source, retained for reference, not shipped", "#193"),
    ("CHANGELOG.md", "KEEP_UPSTREAM_REFERENCE",
     "historical changelog entries document the prior project name", "#193"),

    # Internal Python module namespace + HERMES_* cross-repo contract + legacy
    # state paths — pending the simplicio_agent namespace/migration work.
    ("hermes_cli/*", "compatibility-temporary",
     "internal module namespace pending simplicio_agent rename", "#190"),
    ("hermes_constants.py", "compatibility-temporary", "HERMES_* cross-repo contract constants", "#193"),
    ("hermes_logging.py", "compatibility-temporary", "internal module pending namespace rename", "#190"),
    ("hermes_state.py", "compatibility-temporary", "internal module pending namespace rename", "#190"),
    ("hermes_time.py", "compatibility-temporary", "internal module pending namespace rename", "#190"),
    ("hermes_bootstrap.py", "compatibility-temporary", "internal bootstrap module pending namespace rename", "#190"),
    ("hermes_cli.spec", "compatibility-temporary", "PyInstaller spec references internal module name", "#190"),
    ("gateway/*", "compatibility-temporary",
     "internal implementation imports hermes_cli/hermes_bootstrap and HERMES_* env "
     "contract; not a distinct public surface string", "#190"),
    ("tools/*", "compatibility-temporary",
     "internal implementation imports hermes_cli and HERMES_* env contract", "#190"),
    ("agent/*", "compatibility-temporary",
     "internal implementation imports hermes_cli and HERMES_* env contract", "#190"),
    ("tui_gateway/*", "compatibility-temporary",
     "internal implementation imports hermes_cli and HERMES_* env contract", "#190"),
    ("acp_adapter/*", "compatibility-temporary",
     "internal implementation imports hermes_cli; adapter module docstrings, not "
     "end-user-facing product copy", "#190"),
    ("cron/*", "compatibility-temporary",
     "internal scheduler imports hermes_cli and reads ~/.hermes state paths pending #117", "#117"),
    ("scripts/*", "compatibility-temporary",
     "developer-only scripts (not shipped) reference hermes_cli/HERMES_* internals", "#190"),
    ("rust_ext/*", "compatibility-temporary", "internal PyO3 extension name pending namespace rename", "#190"),
    ("providers/__init__.py", "compatibility-temporary", "internal provider registry references hermes_cli", "#190"),
    ("providers/base.py", "compatibility-temporary", "internal UA string derived from hermes-cli package name", "#118"),
    ("model_tools.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("mcp_serve.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("run_agent.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("batch_runner.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("trajectory_compressor.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("mini_swe_runner.py", "compatibility-temporary", "internal module imports hermes_cli", "#190"),
    ("toolsets.py", "compatibility-temporary", "internal module imports hermes_cli / blueprint identifiers", "#190"),
    ("utils.py", "compatibility-temporary", "internal helper imports hermes_cli", "#190"),
    ("hooks/*", "compatibility-temporary", "internal hook scripts reference hermes_cli/HERMES_* env", "#190"),
    ("acp_registry/*", "compatibility-temporary", "internal registry references hermes_cli", "#190"),

    # Legacy state/migration paths — must MIGRATE_STATE per #117, not error.
    (".env.example", "MIGRATE_STATE", "documents legacy HERMES_* env aliases pending #117 migration", "#117"),
    (".envrc", "MIGRATE_STATE", "documents legacy HERMES_* env aliases pending #117 migration", "#117"),

    # Distribution/packaging identity — real public debt, needs shim+migration (#118).
    ("nix/*", "public-must-migrate", "Nix package/attribute names ship the old brand", "#118"),
    ("packaging/homebrew/*", "public-must-migrate", "Homebrew formula/class name ships the old brand", "#118"),
    ("packaging/*", "public-must-migrate", "packaging metadata ships the old brand", "#118"),
    ("docker/*", "public-must-migrate",
     "Docker image identity, container user/service names and default agent "
     "persona (SOUL.md) ship the old brand to end users", "#118"),
    ("Dockerfile", "public-must-migrate", "image build ships old brand labels/paths", "#118"),
    ("docker-compose.yml", "public-must-migrate", "compose service identity ships the old brand", "#118"),
    ("docker-compose.windows.yml", "public-must-migrate", "compose service identity ships the old brand", "#118"),
    (".dockerignore", "public-must-migrate", "references old brand path layout", "#118"),
    (".hadolint.yaml", "public-must-migrate", "lints old brand Dockerfile", "#118"),
    ("pyproject.toml", "public-must-migrate", "PyPI package/distribution name is the old brand", "#118"),
    ("setup.py", "public-must-migrate", "package build metadata ships the old brand", "#118"),
    ("MANIFEST.in", "public-must-migrate", "package manifest references old brand paths", "#118"),
    ("package.json", "public-must-migrate", "npm package identity is the old brand", "#118"),
    ("flake.nix", "public-must-migrate", "Nix flake package identity is the old brand", "#118"),
    ("constraints-termux.txt", "public-must-migrate", "Termux packaging references old brand", "#118"),
    ("setup-hermes.sh", "public-must-migrate", "installer script name/output is user-facing", "#118"),
    ("cli-config.yaml.example", "public-must-migrate", "user-facing example config documents old brand keys", "#188"),

    # CLI/TUI/Desktop/gateway/apps — the user-facing product surface (#188).
    ("cli.py", "public-must-migrate", "CLI banner/help text is user-facing product identity", "#188"),
    ("ui-tui/*", "public-must-migrate", "TUI package name/README/UI copy is user-facing product identity", "#188"),
    ("apps/*", "public-must-migrate", "installer app title/package identity is user-facing", "#188"),
    ("desktop/*", "public-must-migrate",
     "Desktop app source (non-generated) mixes internal hermes_cli integration "
     "code with user-facing strings; needs line-level review, not blanket allowlisting", "#188"),

    # Distributed skills/plugins — public authorship/branding metadata (#189).
    ("optional-skills/*", "public-must-migrate", "skill frontmatter/docs ship old brand author/product name", "#189"),
    ("skills/*", "public-must-migrate", "skill frontmatter/docs ship old brand author/product name", "#189"),
    ("plugins/*", "public-must-migrate",
     "plugin source mixes internal integration code with user-facing plugin "
     "identity/UI copy; needs line-level review, not blanket allowlisting", "#189"),

    # Locales — product language (#192).
    ("locales/*", "public-must-migrate", "translated user-facing message catalog headers/content", "#192"),

    # Docs/root project files — public docs surface (#189).
    ("docs/*", "public-must-migrate", "public documentation references old brand", "#189"),
    ("AGENTS.md", "public-must-migrate", "root contributor/agent doc is a public-facing surface", "#189"),
    ("README.md", "public-must-migrate", "root README is the primary public surface", "#189"),
    ("README.es.md", "public-must-migrate", "public README translation", "#189"),
    ("README.zh-CN.md", "public-must-migrate", "public README translation", "#189"),
    ("README.ur-pk.md", "public-must-migrate", "public README translation", "#189"),
    ("CONTRIBUTING.md", "public-must-migrate", "public contributor doc", "#189"),
    ("CONTRIBUTING.es.md", "public-must-migrate", "public contributor doc translation", "#189"),
    ("SECURITY.md", "public-must-migrate", "public security policy doc", "#189"),
    ("SECURITY.es.md", "public-must-migrate", "public security policy doc translation", "#189"),
    ("hermes-already-has-routines.md", "public-must-migrate", "public-facing planning doc title/content", "#189"),
    ("datagen-config-examples/*", "public-must-migrate", "example config shipped to users", "#189"),
    ("optional-mcps/*", "public-must-migrate", "distributed MCP config examples", "#191"),
    (".github/*", "compatibility-temporary", "CI/workflow internals, not shipped to end users", "#194"),
    (".gitignore", "KEEP_INTERNAL", "repo-local ignore patterns reference legacy internal paths", "#190"),
    (".plans/*", "historical-fixture", "internal planning notes, not a shipped surface", "#193"),

    # Root CLI launcher wrapper and its legacy compat symlink.
    ("simplicio-agent", "public-must-migrate", "installed CLI launcher banner/behavior is user-facing", "#188"),
    ("hermes", "compatibility-temporary", "legacy `hermes` command symlink kept during alias deprecation window", "#193"),
    ("providers/README.md", "public-must-migrate", "public docs describing provider registry", "#189"),
]


def classify(path: str) -> tuple[str, str, str]:
    for glob, klass, reason, issue in RULES:
        if fnmatch.fnmatch(path, glob):
            return klass, reason, issue
    return "REVIEW", "no rule matched; needs manual triage", "#187"


def main() -> int:
    data = json.loads(REPORT.read_text())
    base = [o for o in data["occurrences"] if o["class"] == "baseline"]
    files = sorted(set(o["path"] for o in base))

    file_class: dict[str, tuple[str, str, str]] = {f: classify(f) for f in files}

    per_class_count = Counter()
    per_class_files = defaultdict(int)
    by_issue = Counter()
    for o in base:
        klass, reason, issue = file_class[o["path"]]
        per_class_count[klass] += 1
        by_issue[issue] += 1
    for f in files:
        klass = file_class[f][0]
        per_class_files[klass] += 1

    manifest = {
        "schema": "simplicio.rename-inventory/v1",
        "generated_from": "tools/rename_guard/scanner.py baseline occurrences",
        "granularity": "file",
        "total_occurrences": len(base),
        "total_files": len(files),
        "unclassified_occurrences": per_class_count.get("REVIEW", 0),
        "by_class": dict(per_class_count),
        "by_class_files": dict(per_class_files),
        "by_owning_issue": dict(by_issue),
        "files": [
            {"path": f, "class": file_class[f][0], "reason": file_class[f][1], "owning_issue": file_class[f][2]}
            for f in files
        ],
    }
    OUT_JSON.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    unclassified = [f for f in files if file_class[f][0] == "REVIEW"]
    print(f"total occurrences: {len(base)} across {len(files)} files")
    print("by class (occurrences):", dict(per_class_count))
    print("by owning issue (occurrences):", dict(by_issue))
    print(f"unclassified files: {len(unclassified)}")
    for f in unclassified:
        print("  REVIEW:", f)
    return 0 if not unclassified else 1


if __name__ == "__main__":
    raise SystemExit(main())
