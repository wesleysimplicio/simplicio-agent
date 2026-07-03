"""Unit tests for agent.telemetry.mcp_session (issue #65)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.telemetry.mcp_session import (
    MCPOperation, MCPSession,
    create_session, record_operation, close_session,
    save_session, load_session, list_sessions,
    session_report,
)


class TestMCPOperation:

    def test_savings_pct_computed(self):
        op = MCPOperation(verb="map", tokens_spent=100, tokens_baseline=500)
        assert op.tokens_saved == 400
        assert op.savings_pct == 80.0

    def test_zero_baseline_no_division_error(self):
        op = MCPOperation(verb="edit", tokens_spent=0, tokens_baseline=0)
        assert op.savings_pct == 0.0

    def test_no_savings_when_baseline_equals_spent(self):
        op = MCPOperation(verb="gate", tokens_spent=500, tokens_baseline=500)
        assert op.savings_pct == 0.0

    def test_default_proof_is_estimated(self):
        op = MCPOperation(verb="test")
        assert op.proof_kind == "estimated"

    def test_to_dict_includes_all_fields(self):
        op = MCPOperation(
            verb="map", duration_ms=42.5, tokens_spent=100,
            tokens_baseline=500, ok=True, proof_kind="estimated",
        )
        d = op.to_dict()
        assert d["verb"] == "map"
        assert d["tokens_spent"] == 100
        assert d["tokens_saved"] == 400


class TestMCPSession:

    def test_empty_session_totals(self):
        s = MCPSession(session_id="test-1", caller_label="test")
        assert s.operation_count == 0
        assert s.error_count == 0
        assert s.total_duration_ms == 0.0
        assert s.total_tokens_spent == 0
        assert s.total_tokens_saved == 0

    def test_session_with_operations(self):
        s = MCPSession(session_id="test-2", caller_label="test")
        record_operation(s, "map", duration_ms=50, tokens_spent=100, tokens_baseline=500)
        record_operation(s, "edit", duration_ms=30, tokens_spent=50, tokens_baseline=200)
        assert s.operation_count == 2
        assert s.error_count == 0
        assert s.total_duration_ms == 80.0
        assert s.total_tokens_spent == 150
        assert s.total_tokens_baseline == 700
        assert s.total_tokens_saved == 550

    def test_error_counting(self):
        s = MCPSession(session_id="test-3")
        record_operation(s, "gate", ok=False, error="permission denied")
        record_operation(s, "map", ok=True)
        assert s.error_count == 1
        assert s.operation_count == 2

    def test_overall_savings_pct(self):
        s = MCPSession(session_id="test-4")
        record_operation(s, "map", tokens_spent=100, tokens_baseline=500)
        record_operation(s, "edit", tokens_spent=50, tokens_baseline=200)
        # total_baseline=700, total_spent=150, saved=550, pct=78.57
        assert s.overall_savings_pct == pytest.approx(78.57, rel=1e-2)

    def test_to_dict_roundtrip(self):
        s = MCPSession(
            session_id="rt-1",
            caller_label="test-runner",
            mode="tool",
            cost_attribution="agent",
        )
        record_operation(s, "map", duration_ms=42.0, tokens_spent=100, tokens_baseline=500)
        d = s.to_dict()
        assert d["session_id"] == "rt-1"
        assert d["caller_label"] == "test-runner"
        assert len(d["operations"]) == 1
        assert d["total_tokens_saved"] == 400

    def test_to_report_text_includes_session_info(self):
        s = MCPSession(session_id="report-1", caller_label="claude", mode="tool")
        record_operation(s, "map", duration_ms=42.5, tokens_spent=100, tokens_baseline=500)
        text = s.to_report_text()
        assert "report-1" in text
        assert "claude" in text
        assert "tool" in text
        assert "map" in text
        assert "42.5" in text


class TestSessionLifecycle:

    def test_create_session_defaults(self):
        s = create_session(caller_label="test")
        assert s.caller_label == "test"
        assert s.mode == "tool"
        assert s.cost_attribution == "agent"
        assert s.operation_count == 0
        # session_id should be a valid UUID
        uuid.UUID(s.session_id)

    def test_create_session_with_id(self):
        s = create_session(caller_label="test", mode="delegated", cost_attribution="caller", session_id="my-session")
        assert s.session_id == "my-session"
        assert s.mode == "delegated"
        assert s.cost_attribution == "caller"

    def test_record_operation_returns_op(self):
        s = create_session(caller_label="test")
        op = record_operation(
            s, "gate", duration_ms=10, tokens_spent=0,
            tokens_baseline=100, ok=True, proof_kind="measured",
        )
        assert isinstance(op, MCPOperation)
        assert op.verb == "gate"
        assert op.tokens_saved == 100
        assert op.proof_kind == "measured"

    def test_close_session_sets_ended_at(self):
        s = create_session(caller_label="test")
        record_operation(s, "map", tokens_spent=10, tokens_baseline=50)
        assert s.ended_at is None
        close_session(s)
        assert s.ended_at is not None


class TestSessionPersistence:

    def test_save_and_load_session(self, tmp_path: Path):
        import agent.telemetry.mcp_session as mcp_module
        mcp_module._DEFAULT_LEDGER_DIR = tmp_path / "ledger"
        s = create_session(caller_label="test", session_id="persist-1")
        record_operation(s, "map", duration_ms=42.0, tokens_spent=100, tokens_baseline=500)
        save_session(s)
        loaded = load_session("persist-1")
        assert loaded is not None
        assert loaded.session_id == "persist-1"
        assert loaded.caller_label == "test"
        assert loaded.operation_count == 1
        assert loaded.total_tokens_saved == 400

    def test_load_nonexistent_session_returns_none(self):
        assert load_session("nonexistent") is None

    def test_list_sessions_empty_ledger(self):
        import agent.telemetry.mcp_session as mcp_module
        import tempfile
        mcp_module._DEFAULT_LEDGER_DIR = Path(tempfile.mkdtemp()) / "ledger"
        assert list_sessions() == []


class TestSessionReport:

    def test_report_unknown_session(self):
        report = session_report(session_id="does-not-exist")
        assert "not found" in report

    def test_report_no_sessions_at_all(self):
        import agent.telemetry.mcp_session as mcp_module
        import tempfile
        mcp_module._DEFAULT_LEDGER_DIR = Path(tempfile.mkdtemp()) / "ledger"
        report = session_report()
        assert "No MCP" in report

    def test_report_json_output_for_session(self, tmp_path: Path):
        import agent.telemetry.mcp_session as mcp_module
        mcp_module._DEFAULT_LEDGER_DIR = tmp_path / "ledger"
        s = create_session(caller_label="test", session_id="json-sess")
        record_operation(s, "map", tokens_spent=100, tokens_baseline=500)
        save_session(s)
        report = session_report(session_id="json-sess", json_output=True)
        data = json.loads(report)
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["session_id"] == "json-sess"