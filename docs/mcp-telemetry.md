# MCP Telemetry — Session instrumentation and usage reports

- Status: implemented
- Date: 2026-07-03
- Related: issue #65, #64 (provider-mode contract), simplicio-runtime#2780 (MCP daemon),
  agent/telemetry/* (existing dormant stack)

## Overview

When a frontier LLM calls the Simplicio Agent via MCP, each call is an
**instrumentable session**: we capture what was done, what it cost, and
how much was saved vs doing it without the agent. This is the product
delivering proof of value — not a promise.

The existing telemetry stack (`token_savings.py`, `receipts.py`,
`savings_report.py`, `gain_analytics.py`, `dashboard.py`, `stage_timer.py`)
was **verified dormant** — complete but with zero production callers.
This feature bridges that stack into the MCP request boundary.

## Architecture

```
MCP Request
    |
    v
create_session() ─── MCPSession (session_id, caller, mode)
    |
    +-- record_operation() ─── per-verb: latency, tokens, savings
    |       |
    |       +-- stage_timer.record_stage()     (latency tracking)
    |       +-- token_savings.record()          (JSONL savings ledger)
    |       +-- receipts.record_receipt()      (content-addressable index)
    |
    +-- close_session() ─── persist + report
            |
            +-- save_session()  (JSON file, ~/.hermes/telemetry/mcp_sessions/)
            +-- savings_report.build_report()  (weekly-style aggregation)
            +-- gain_analytics.aggregate()     (cross-session trends)
```

## Key concepts

### Session

A **session** corresponds to one MCP request. It carries:

- `session_id` (UUID)
- `caller_label` (identifies the LLM/host, e.g. "claude-code@host")
- `mode` (from provider-mode contract: standalone/tool/delegated)
- `cost_attribution` (who pays: "agent" or "caller")
- `operations` (list of recorded operations within the session)

### Operation

Each **operation** captures one verb within the session:

- `verb`: the MCP tool or action name (e.g. "map", "edit", "gate", "messages_send")
- `duration_ms`: wall-clock latency
- `tokens_spent`: tokens actually consumed by the operation
- `tokens_baseline`: what it would cost WITHOUT the agent (honest baseline)
- `tokens_saved`: baseline - spent
- `proof_kind`: "measured" (real measurement) or "estimated" (best-effort)
- `ok`: success/failure
- `error`: error message on failure

### Baseline honesty

Per the savings-event/v1 spec (simplicio-runtime#2775):

| Operation | Baseline (without agent) | Why honest |
|-----------|------------------------|------------|
| `map` | LLM re-reading the file tree | Directly observable — the agent knows the tree |
| `edit` | LLM rewriting the whole file | The agent measures the edit delta |
| `gate` | LLM re-deriving the same check | The agent already ran the check |
| `test` | LLM manually constructing test input | The agent used deterministic generation |

Operations without a measurable baseline are marked `proof_kind: "estimated"`
with an explicit note — never a fabricated number.

## CLI usage

```bash
# Report a single session
python -m agent.telemetry.mcp_session report --id <session_id>

# Report all sessions for a caller
python -m agent.telemetry.mcp_session report --caller claude-code

# JSON output
python -m agent.telemetry.mcp_session report --id <session_id> --json

# List all sessions
python -m agent.telemetry.mcp_session report
```

## Integration with existing telemetry

### token_savings.py

Each operation records a token-saving event via `record_token_saving()`.
This feeds the existing JSONL ledger and is consumable by the existing
`savings_report` and `gain_analytics` modules.

### stage_timer.py

Each session emits a `record_stage()` call with the session ID and duration.
This makes all MCP session durations visible in the existing `dashboard`
output and the `/perf` web view.

### receipts.py

Deterministic operations (map, edit, gate) record content-addressable receipts.
Duplicate work can short-circuit by looking up the receipt hash.

## Security and privacy

- **No credentials in telemetry:** `provider_ref` is redacted with the
  `<redacted>` marker when the `redacted` flag is set.
- **No caller payload content:** only operation names, durations, and token
  counts are captured — never message content, files, or secrets.
- **Best-effort persistence:** disk write failures never raise into the hot
  path (silent failure, matching the existing telemetry convention).

## Testing

The module is designed for isolated testing:

```python
from agent.telemetry.mcp_session import create_session, record_operation, close_session

session = create_session(caller_label="test-runner", mode="tool")
record_operation(session, "map", duration_ms=42.5, tokens_spent=100, tokens_baseline=500)
close_session(session)
assert session.overall_savings_pct == 80.0
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_MCP_TELEMETRY_DIR` | `~/.hermes/telemetry/mcp_sessions/` | Override ledger directory |
| `HERMES_TELEMETRY_LOG` | `~/.hermes/telemetry.jsonl` | Stage timer log path |