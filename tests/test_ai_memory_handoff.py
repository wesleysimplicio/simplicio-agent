"""
tests/test_ai_memory_handoff.py

Tests for agent/ai_memory/cross_vendor.py — issue #38.
"""

import sys
import os

# Allow imports from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.ai_memory.cross_vendor import (
    CrossVendorHandoff,
    HandoffRecord,
    snapshot_fts_search,
)


# ---------------------------------------------------------------------------
# 1. HandoffRecord is created correctly via export()
# ---------------------------------------------------------------------------

def test_export_creates_handoff_record():
    session = {"goal": "implement handoff", "turns": 3, "vendor": "claude-code"}
    record = CrossVendorHandoff.export(
        session,
        from_vendor="claude-code",
        to_vendor="codex",
    )

    assert isinstance(record, HandoffRecord)
    assert record.from_vendor == "claude-code"
    assert record.to_vendor == "codex"
    assert record.memory_snapshot == session
    assert record.session_id  # non-empty auto-generated UUID
    assert record.timestamp   # non-empty ISO timestamp


# ---------------------------------------------------------------------------
# 2. import_from() returns a correct copy of the snapshot
# ---------------------------------------------------------------------------

def test_import_from_returns_snapshot_copy():
    original_snapshot = {"task": "cross-vendor handoff", "status": "done", "priority": 1}
    record = HandoffRecord(
        from_vendor="codex",
        to_vendor="simplicio",
        session_id="abc-123",
        memory_snapshot=original_snapshot,
    )

    restored = CrossVendorHandoff.import_from(record)

    assert restored == original_snapshot
    # Mutation of the returned dict must not affect the record
    restored["injected"] = True
    assert "injected" not in record.memory_snapshot


# ---------------------------------------------------------------------------
# 3. Full round-trip: export → import preserves data
# ---------------------------------------------------------------------------

def test_round_trip_preserves_snapshot():
    session = {
        "model": "claude-sonnet-4",
        "context_tokens": 4096,
        "active_skill": "github-pr-workflow",
    }
    record = CrossVendorHandoff.export(
        session,
        from_vendor="simplicio",
        to_vendor="claude-code",
        session_id="fixed-id-001",
    )
    restored = CrossVendorHandoff.import_from(record)

    assert restored == session
    assert record.session_id == "fixed-id-001"


# ---------------------------------------------------------------------------
# 4. snapshot_fts_search — basic keyword match
# ---------------------------------------------------------------------------

def test_fts_search_finds_matching_entry():
    snapshot = {
        "goal": "Build cross-vendor handoff support",
        "vendor": "claude-code",
        "status": "in-progress",
    }
    results = snapshot_fts_search(snapshot, "handoff")
    assert "goal" in results
    assert "vendor" not in results
    assert "status" not in results


# ---------------------------------------------------------------------------
# 5. snapshot_fts_search — multi-term AND semantics
# ---------------------------------------------------------------------------

def test_fts_search_multi_term_and():
    snapshot = {
        "note": "Claude Code handles the handoff to Codex",
        "other": "Codex only",
        "unrelated": "nothing here",
    }
    # Both terms must be present
    results = snapshot_fts_search(snapshot, "claude handoff")
    assert "note" in results
    assert "other" not in results
    assert "unrelated" not in results


# ---------------------------------------------------------------------------
# 6. snapshot_fts_search — empty query returns all entries
# ---------------------------------------------------------------------------

def test_fts_search_empty_query_returns_all():
    snapshot = {"a": 1, "b": 2, "c": 3}
    results = snapshot_fts_search(snapshot, "")
    assert results == snapshot


# ---------------------------------------------------------------------------
# 7. HandoffRecord default timestamp is set and valid ISO-8601
# ---------------------------------------------------------------------------

def test_handoff_record_timestamp_is_iso():
    from datetime import datetime, timezone
    record = HandoffRecord(
        from_vendor="x",
        to_vendor="y",
        session_id="s1",
        memory_snapshot={},
    )
    # Should parse without error
    dt = datetime.fromisoformat(record.timestamp)
    assert dt.tzinfo is not None  # timezone-aware
