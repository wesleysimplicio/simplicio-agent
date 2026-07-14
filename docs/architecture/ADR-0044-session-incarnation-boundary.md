# ADR-0044: bounded session-incarnation boundary for modular Agent turns

- Status: accepted for the #221 architecture slice
- Date: 2026-07-14
- Related: #221, `agent/session.py`, `agent/turn_engine.py`, ADR-0028

## Context

The Agent already has focused contracts for turn state, provider lifecycle,
tool invocation, operational self-model receipts, and the Simplicio bridge.
Without a shared session boundary, those contracts can be composed with
different prompt/tool/provider identities while a long-lived session is still
treated as the same prefix-cache incarnation.  The earlier `turn_prep` seam
does not own this identity or turn lifecycle.

## Decision

`agent.session.AgentSession` is the narrow compatibility seam for one session
incarnation.  `SessionSnapshot` records only non-secret fingerprints for the
system prompt and toolset, plus provider route, cognition digest, and bridge
generation.  `assert_compatible()` rejects changes to any of those values;
callers must create a new incarnation instead.

`AgentSession.begin_turn()` creates a session-correlated `TurnContext` and
delegates every state transition to `TurnEngine`.  Completion, failure,
cancellation, active-turn accounting, and idle close are bounded here, while
provider calls, tool execution, cognition updates, bridge effects, SessionDB,
and the public `AIAgent` facade remain owned by their existing modules.

This is a contract-only migration step.  Existing surfaces are not rewired in
this slice, preserving import and callback compatibility; a later integration
slice may adopt the boundary behind an adapter after cross-surface evidence.

## Consequences

- Prompt/toolset identity cannot drift silently within a session incarnation.
- Turn state has one explicit session owner and one existing transition engine.
- No prompt, tool definition, credential, or Runtime transcript crosses the
  boundary; only hashes and measured metadata are retained.
- The contract is testable without provider SDKs, a Runtime binary, or network.
- Legacy `AIAgent` wiring remains unchanged until a separately scoped rollout.

## Acceptance evidence

`tests/agent/test_session.py` covers deterministic tool ordering, secret-free
fingerprints, incarnation drift rejection, shared TurnEngine transitions,
foreign/closed turn rejection, active-turn close protection, and terminal
failure accounting.
