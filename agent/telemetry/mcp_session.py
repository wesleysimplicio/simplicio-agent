"""MCP session telemetry — instrumented MCP request tracking (issue #65).

This module bridges the existing dormant telemetry stack
(token_savings.py, stage_timer.py, receipts.py, savings_report.py,
gain_analytics.py, dashboard.py) into the MCP request boundary.

Every MCP request opens an instrumented session that captures:
- session_id, caller, mode (from provider_mode contract)
- per-operation: verb, tokens spent, tokens saved, latency, result
- savings events with baseline vs spent (honest provenance)
- cost attribution to caller (delegated mode) or agent

CLI usage:
    python -m agent.telemetry.mcp_session report --id <session_id>
    python -m agent.telemetry.mcp_session report --caller claude-code
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agent.telemetry.stage_timer import record_stage

logger = logging.getLogger(__name__)

def _default_ledger_dir() -> Path:
    """Return ``<HERMES_HOME>/telemetry/mcp_sessions``.

    Derived from ``hermes_constants.get_hermes_home()`` instead of a
    hardcoded ``Path.home() / ".simplicio_agent"`` so it honors
    ``SIMPLICIO_AGENT_HOME``/``HERMES_HOME`` and any migration (issue #117).
    """
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "telemetry" / "mcp_sessions"


# Constants. ``_DEFAULT_LEDGER_DIR`` stays a module attribute (not just a
# function) for backward compatibility with callers/tests that read or
# monkeypatch ``mcp_session._DEFAULT_LEDGER_DIR`` directly.
_DEFAULT_LEDGER_DIR = _default_ledger_dir()
_ENV_LEDGER_DIR = "HERMES_MCP_TELEMETRY_DIR"

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

MCP_VERBS = frozenset({
    "conversations_list", "conversation_get", "messages_read",
    "attachments_fetch", "events_poll", "events_wait",
    "messages_send", "channels_list", "permissions_list_open",
    "permissions_respond", "session_report", "map", "edit",
    "gate", "test", "evidence",
})

@dataclass
class MCPOperation:
    """A single operation recorded within an MCP telemetry session."""
    verb: str
    duration_ms: float = 0.0
    tokens_spent: int = 0
    tokens_baseline: int = 0
    _tokens_saved: int = 0  # internal, use tokens_saved property  # computed as max(0, tokens_baseline - tokens_spent) in record_operation
    ok: bool = True
    proof_kind: str = "estimated"  # "measured" | "estimated"
    error: Optional[str] = None

    ts: str = field(default_factory=_utc_now)

    @property
    def savings_pct(self) -> float:
        if self.tokens_baseline <= 0:
            return 0.0
        return round(100.0 * self.tokens_saved / self.tokens_baseline, 2)

    @property
    def tokens_saved(self) -> int:
        if self._tokens_saved == 0 and self.tokens_baseline > 0:
            return max(0, self.tokens_baseline - self.tokens_spent)
        return self._tokens_saved

    @tokens_saved.setter
    def tokens_saved(self, value: int) -> None:
        object.__setattr__(self, '_tokens_saved', value)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['tokens_saved'] = self.tokens_saved
        return d

@dataclass
class MCPSession:
    """One instrumented MCP request session."""
    session_id: str
    caller_label: str = "unknown"
    mode: str = "tool"  # "standalone" | "tool" | "delegated"
    cost_attribution: str = "agent"
    started_at: str = field(default_factory=_utc_now)
    ended_at: Optional[str] = None
    operations: List[MCPOperation] = field(default_factory=list)

    @property
    def total_duration_ms(self) -> float:
        return sum(op.duration_ms for op in self.operations)

    @property
    def total_tokens_spent(self) -> int:
        return sum(op.tokens_spent for op in self.operations)

    @property
    def total_tokens_baseline(self) -> int:
        return sum(op.tokens_baseline for op in self.operations)

    @property
    def total_tokens_saved(self) -> int:
        return max(0, self.total_tokens_baseline - self.total_tokens_spent)

    @property
    def overall_savings_pct(self) -> float:
        if self.total_tokens_baseline <= 0:
            return 0.0
        return round(100.0 * self.total_tokens_saved / self.total_tokens_baseline, 2)

    @property
    def operation_count(self) -> int:
        return len(self.operations)

    @property
    def error_count(self) -> int:
        return sum(1 for op in self.operations if not op.ok)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "caller_label": self.caller_label,
            "mode": self.mode,
            "cost_attribution": self.cost_attribution,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "operation_count": self.operation_count,
            "error_count": self.error_count,
            "total_duration_ms": round(self.total_duration_ms, 3),
            "total_tokens_spent": self.total_tokens_spent,
            "total_tokens_baseline": self.total_tokens_baseline,
            "total_tokens_saved": self.total_tokens_saved,
            "overall_savings_pct": self.overall_savings_pct,
            "operations": [op.to_dict() for op in self.operations],
        }

    def to_report_text(self) -> str:
        result = [
            "MCP Session Report",
            "=" * 60,
            f"Session ID:       {self.session_id}",
            f"Caller:           {self.caller_label}",
            f"Mode:             {self.mode}",
            f"Cost attribution: {self.cost_attribution}",
            f"Started:          {self.started_at}",
            f"Ended:            {self.ended_at or chr(39)*4}",
            f"Operations:       {self.operation_count} ({self.error_count} errors)",
            f"Total duration:   {self.total_duration_ms:.1f} ms",
            f"Tokens spent:     {self.total_tokens_spent}",
            f"Tokens baseline:  {self.total_tokens_baseline}",
            f"Tokens saved:     {self.total_tokens_saved}",
            f"Savings:          {self.overall_savings_pct}%",
            "",
            "Operations:",
            "-" * 60,
        ]
        for op in self.operations:
            status = "OK" if op.ok else "ERROR"
            result.append(f"  {op.verb:<30} {status} {op.duration_ms:>8.1f}ms spent={op.tokens_spent} baseline={op.tokens_baseline} saved={op.tokens_saved} proof={op.proof_kind}")
            if op.error:
                result.append(f"    error: {op.error}")
        return chr(10).join(result)

def _ledger_dir() -> Path:
    override = os.environ.get(_ENV_LEDGER_DIR)
    return Path(override) if override else _DEFAULT_LEDGER_DIR

def _session_path(session_id: str) -> Path:
    return _ledger_dir() / f"{session_id}.json"

def _ensure_ledger_dir() -> None:
    _ledger_dir().mkdir(parents=True, exist_ok=True)

def save_session(session: MCPSession) -> None:
    """Persist a completed MCP session to disk. Best-effort."""
    try:
        _ensure_ledger_dir()
        path = _session_path(session.session_id)
        path.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
        record_stage(
            f"mcp_session:{session.session_id}",
            session.total_duration_ms,
            provider=session.caller_label,
            tool=session.mode,
            ok=session.error_count == 0,
            meta={"operations": session.operation_count, "savings_pct": session.overall_savings_pct},
        )
    except Exception as exc:
        logger.warning("Failed to save MCP session %s: %s", session.session_id, exc)

def load_session(session_id: str) -> Optional[MCPSession]:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        ops = []
        for op_data in data.get("operations", []):
            if "tokens_saved" in op_data:
                op_data["_tokens_saved"] = op_data.pop("tokens_saved")
            ops.append(MCPOperation(**op_data))
        return MCPSession(
            session_id=data["session_id"],
            caller_label=data.get("caller_label", "unknown"),
            mode=data.get("mode", "tool"),
            cost_attribution=data.get("cost_attribution", "agent"),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at"),
            operations=ops,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to load session %s: %s", session_id, exc)
        return None

def list_sessions(caller_label: Optional[str] = None) -> List[MCPSession]:
    ledger = _ledger_dir()
    if not ledger.exists():
        return []
    sessions = []
    for f in sorted(ledger.iterdir(), reverse=True):
        if f.suffix == ".json":
            s = load_session(f.stem)
            if s and (not caller_label or s.caller_label == caller_label):
                sessions.append(s)
    return sessions

def create_session(
    *,
    caller_label: str = "unknown",
    mode: str = "tool",
    cost_attribution: str = "agent",
    session_id: Optional[str] = None,
) -> MCPSession:
    return MCPSession(
        session_id=session_id or str(uuid.uuid4()),
        caller_label=caller_label,
        mode=mode,
        cost_attribution=cost_attribution,
    )

def record_operation(
    session: MCPSession,
    verb: str,
    *,
    duration_ms: float = 0.0,
    tokens_spent: int = 0,
    tokens_baseline: int = 0,
    ok: bool = True,
    proof_kind: str = "estimated",
    error: Optional[str] = None
,
) -> MCPOperation:
    op = MCPOperation(
        verb=verb,
        duration_ms=round(duration_ms, 3),
        tokens_spent=tokens_spent,
        tokens_baseline=tokens_baseline,
        _tokens_saved=max(0, tokens_baseline - tokens_spent),
        ok=ok, proof_kind=proof_kind, error=error,
    )
    session.operations.append(op)
    return op

def close_session(session: MCPSession) -> None:
    """Finalise and persist a session."""
    session.ended_at = _utc_now()
    save_session(session)
    logger.info(
        "MCP session %s complete: %d ops, %dms, %d tokens saved (%.1f%%). caller=%s mode=%s",
        session.session_id, session.operation_count,
        int(session.total_duration_ms), session.total_tokens_saved,
        session.overall_savings_pct, session.caller_label, session.mode,
    )

def session_report(
    *,
    session_id: Optional[str] = None,
    caller_label: Optional[str] = None,
    json_output: bool = False,
) -> str:
    """Generate a session report."""
    if session_id:
        s = load_session(session_id)
        if not s:
            return f"Session {session_id!r} not found."
        sessions = [s]
    elif caller_label:
        sessions = list_sessions(caller_label=caller_label)
        if not sessions:
            return f"No sessions found for caller {caller_label!r}."
    else:
        sessions = list_sessions()
        if not sessions:
            return "No MCP telemetry sessions found."

    if json_output:
        data = {
            "sessions": [s.to_dict() for s in sessions],
            "summary": {
                "total_sessions": len(sessions),
                "total_operations": sum(s.operation_count for s in sessions),
                "total_duration_ms": round(sum(s.total_duration_ms for s in sessions), 3),
                "total_tokens_spent": sum(s.total_tokens_spent for s in sessions),
                "total_tokens_saved": sum(s.total_tokens_saved for s in sessions),
            },
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    result = []
    for s in sessions:
        result.append(s.to_report_text())
        result.append("")
    result.append(f"Total sessions: {len(sessions)}")
    result.append(f"Total operations: {sum(s.operation_count for s in sessions)}")
    result.append(f"Total duration: {round(sum(s.total_duration_ms for s in sessions), 1)} ms")
    result.append(f"Total tokens spent: {sum(s.total_tokens_spent for s in sessions)}")
    result.append(f"Total tokens saved: {sum(s.total_tokens_saved for s in sessions)}")
    return chr(10).join(result)

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    import argparse
    p = argparse.ArgumentParser(prog="simplicio-agent session report")
    p.add_argument("--id", dest="session_id", help="Session ID")
    p.add_argument("--caller", dest="caller_label", help="Filter by caller")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(argv)
    print(session_report(session_id=args.session_id, caller_label=args.caller_label, json_output=args.json))
    return 0

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

__all__ = [
    "MCPOperation", "MCPSession",
    "create_session", "record_operation", "close_session",
    "save_session", "load_session", "list_sessions",
    "session_report", "main",
]