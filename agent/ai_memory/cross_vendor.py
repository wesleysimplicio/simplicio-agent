"""
agent/ai_memory/cross_vendor.py

Cross-vendor handoff support for ai-memory (issue #38).

Implements:
  - HandoffRecord  — dataclass carrying a memory snapshot between vendors
  - CrossVendorHandoff — export/import helpers
  - snapshot_fts_search — FTS5-style keyword search over a memory snapshot
                           (pure stdlib, no sqlite)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class HandoffRecord:
    """Portable record that transfers memory state between AI vendors.

    Attributes:
        from_vendor:     Name of the source vendor/agent (e.g. "claude-code").
        to_vendor:       Name of the target vendor/agent (e.g. "codex").
        session_id:      Unique identifier for the originating session.
        memory_snapshot: Arbitrary key→value mapping of memory entries.
        timestamp:       UTC ISO-8601 creation timestamp.
    """

    from_vendor: str
    to_vendor: str
    session_id: str
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Handoff engine
# ---------------------------------------------------------------------------

class CrossVendorHandoff:
    """Export and import memory snapshots across AI vendor boundaries."""

    # ------------------------------------------------------------------ #
    # Export                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def export(
        session: dict[str, Any],
        *,
        from_vendor: str = "unknown",
        to_vendor: str = "unknown",
        session_id: str | None = None,
    ) -> HandoffRecord:
        """Wrap *session* memory into a portable HandoffRecord.

        Args:
            session:    Dict of memory key→value pairs for the current session.
            from_vendor: Originating vendor name.
            to_vendor:   Destination vendor name.
            session_id:  Optional explicit session ID; auto-generated if omitted.

        Returns:
            A HandoffRecord ready to serialise or hand to the target vendor.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        return HandoffRecord(
            from_vendor=from_vendor,
            to_vendor=to_vendor,
            session_id=session_id,
            memory_snapshot=dict(session),
        )

    # ------------------------------------------------------------------ #
    # Import                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def import_from(record: HandoffRecord) -> dict[str, Any]:
        """Extract the memory snapshot from a HandoffRecord.

        Args:
            record: A HandoffRecord received from another vendor.

        Returns:
            A copy of the memory snapshot dict, ready for injection into
            the receiving agent's context.
        """
        return dict(record.memory_snapshot)


# ---------------------------------------------------------------------------
# FTS5-style search (stdlib, no sqlite)
# ---------------------------------------------------------------------------

def snapshot_fts_search(
    snapshot: dict[str, Any],
    query: str,
    *,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Full-text search over a memory snapshot.

    Tokenises *query* into individual terms and returns every entry whose
    key or stringified value contains **all** of the terms (AND semantics,
    same as SQLite FTS5 default).

    Args:
        snapshot:       The memory dict to search.
        query:          Whitespace-separated search terms.
        case_sensitive: When *False* (default) matching is case-insensitive.

    Returns:
        A filtered dict containing only the matching entries.

    Examples:
        >>> snap = {"goal": "Build handoff support", "vendor": "claude"}
        >>> snapshot_fts_search(snap, "handoff")
        {'goal': 'Build handoff support'}
    """
    terms = query.split() if case_sensitive else query.lower().split()

    if not terms:
        return dict(snapshot)

    results: dict[str, Any] = {}
    for key, value in snapshot.items():
        haystack = f"{key} {value}"
        if not case_sensitive:
            haystack = haystack.lower()

        if all(term in haystack for term in terms):
            results[key] = value

    return results
