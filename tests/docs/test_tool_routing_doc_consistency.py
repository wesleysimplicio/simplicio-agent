"""Guard against the CLI-first/MCP-fallback tool-routing doc contradiction.

Issue #212: this repo used to carry two conflicting statements of the
tool-routing hierarchy — the "Unification" section of ``AGENTS.md`` said the
Simplicio CLI is primary and MCP is fallback only, while the separate "Tool
routing" section (and ``ADR-0003``) paired "Hermes-native tools first" with
"Simplicio CLI/MCP second" in a way that read as CLI and MCP being one
interchangeable, equal-priority option.

``AGENTS.md`` § "Tool routing" is now the single canonical source (see the
"Canonical source (issue #212 ...)" callout there). This test asserts:

1. The canonical section still exists and still states the CLI-primary/
   MCP-fallback hierarchy explicitly.
2. The retired, ambiguous phrasing ("Simplicio CLI/MCP second" as a bare
   pairing, with no CLI-primary/MCP-fallback qualifier) does not reappear
   anywhere in the repo's tracked markdown docs.
3. Any doc that still mentions "Hermes-native tools first" (the reasoning/
   coordination half of the hierarchy) also points back at the canonical
   ``AGENTS.md`` section rather than re-deriving the order on its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that are vendored/example content, not this project's own
# operational docs -- excluded so the guard doesn't chase third-party or
# templated prose that isn't part of the routing doctrine.
EXCLUDED_PREFIXES = (
    "archive/",
    "optional-skills/finance/",
    "skills/creative/popular-web-designs/",
    "website/",
    "node_modules/",
)

# The retired phrasing: "Hermes-native tools first" paired with a bare
# "Simplicio CLI/MCP second" (no primary/fallback qualifier attached) is the
# exact contradiction issue #212 exists to eliminate.
RETIRED_PHRASE = "Simplicio CLI/MCP second"

CANONICAL_MARKERS = (
    "Canonical source (issue #212",
    "primary execution surface",
    "MCP is fallback transport only",
)


def _tracked_markdown_files() -> list[Path]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        paths.append(REPO_ROOT / line)
    return paths


def test_agents_md_states_canonical_cli_first_mcp_fallback_hierarchy():
    agents_md = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for marker in CANONICAL_MARKERS:
        assert marker in agents_md, (
            f"AGENTS.md is missing canonical routing marker {marker!r} -- "
            "the single source of truth for CLI-first/MCP-fallback routing "
            "must live in AGENTS.md 'Tool routing' (issue #212)."
        )


def test_no_doc_repeats_the_retired_ambiguous_pairing():
    offenders = []
    for path in _tracked_markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if RETIRED_PHRASE in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Retired, ambiguous routing phrasing "
        f"{RETIRED_PHRASE!r} found in: {offenders}. Link to AGENTS.md "
        "'Tool routing' instead of restating the hierarchy (issue #212)."
    )


def test_docs_mentioning_hermes_native_first_link_back_to_canonical_source():
    offenders = []
    for path in _tracked_markdown_files():
        rel = path.relative_to(REPO_ROOT)
        if rel == Path("AGENTS.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "Hermes-native tools first" not in text:
            continue
        if "AGENTS.md" not in text or "Tool routing" not in text:
            offenders.append(str(rel))
    assert not offenders, (
        "These docs restate the 'Hermes-native tools first' routing order "
        "without linking back to the canonical AGENTS.md 'Tool routing' "
        f"section: {offenders} (issue #212)."
    )
