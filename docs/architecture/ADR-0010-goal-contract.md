# ADR-0010: `simplicio.goal-contract/v1`

**Status:** Accepted (2026-07-13).  
**Owner:** Simplicio Agent goal-control surface.  
**Code:** `agent/goal_contract.py`, `tests/agent/test_goal_contract.py`, and
`fixtures/goal-contract/`.

## Decision

Goals are represented by one immutable, resumable value object.  The object
contains the objective, acceptance criteria, structured facts, inferences,
open questions, evidence receipts, watcher requirements, and an explicit
state.  The schema identifier is `simplicio.goal-contract/v1`; changing the
meaning of an existing field requires a new schema version.

The objective and acceptance criteria are immutable after construction.  Each
is hashed with SHA-256 over canonical JSON (`objective` as a string and
`acceptance_criteria` as an ordered list).  The hashes travel in serialized
forms and are checked on resume, so stale or tampered goal state cannot be
silently adopted.

## Honest terminal states

`completed_verified` means the contract was completed *and* its verification
requirements were met.  It requires at least one verified evidence reference,
every required watcher to be satisfied with a non-failed recomputation, and no
blocking open question.  `completed_unverified` is available when work is
complete but proof is absent; it is terminal and deliberately does not claim
verification.  `failed` and `cancelled` are also terminal states.  `blocked`
is intentionally resumable, like `paused`, so a temporary dependency does
not become a dishonest failure.  No terminal state can be resumed or
transitioned to another state.

Every mutation is a pure value transition returning a new frozen dataclass.
`to_dict`/`from_dict` and `to_json`/`from_json` preserve all fields, including
state and receipts, allowing a paused or blocked goal to resume after process
restart.  The `to_resume_*` and `from_resume_*` names are aliases for callers
that make persistence explicit.

## Boundaries

This module owns the goal contract's data and invariants only.  It does not
inject prompts, execute tools, alter task-envelope lifecycle, or run watchers.
Evidence producers and watcher implementations report receipts into the
contract; only the contract transition gate decides whether a verified
completion claim is honest.  Integration with prompts, tools, task envelopes,
and capability catalogs remains separate work.
