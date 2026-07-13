# ADR-0010: Runtime-first execution and mandatory capability closure

**Status:** Accepted (2026-07-13).  
**Owner:** @wesleysimplicio.  
**Normative language:** `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are used as requirements.  
**Related:** `AGENTS.md#tool-routing`, ADR-0003, ADR-0009, `simplicio-runtime#3195`.

## Context

Simplicio Agent is one system with two distinct responsibilities:

- Hermes/backend supplies reasoning, conversation, planning, interpretation, and coordination.
- Simplicio Runtime supplies execution, deterministic mutation, validation, evidence, compact output, cache, parallelism, and recovery.

A policy that sends reading, searching, Git, tests, or diff inspection directly to native Hermes tools as the normal path prevents the Runtime from measuring and reducing those costs. It also hides capability gaps instead of turning them into product improvements.

## Decision

### 1. Responsibility boundary

Hermes **MUST** reason and coordinate. Hermes **MUST NOT** become the preferred execution layer when the Runtime can execute the action.

Every executable action **MUST** attempt a Simplicio Runtime surface first. This includes, without limitation:

- file reading and repository search;
- Git status, history, branch, and other repository operations;
- diff generation and inspection;
- tests, builds, lint, formatting, and validation;
- file mutation, checkpoints, evidence, and delivery operations;
- shell commands and subprocesses.

The Runtime may supervise an existing host executable. For example, `simplicio shell compact -- git status` counts as Runtime execution because the Runtime owns invocation, output limits, telemetry, and receipts. First-class compiled commands remain preferable when they provide stronger contracts.

### 2. Transport order

Execution order is mandatory:

1. Simplicio CLI (`simplicio <command>`);
2. Simplicio MCP only when CLI is unavailable or an explicitly configured warm MCP path is required;
3. a native Hermes execution tool only as a temporary capability exception.

A native tool is not a peer or permanent alternative to the Runtime.

### 3. Capability-closure obligation

When the Runtime cannot execute an action but a native tool can, the agent **MAY** use the native tool to unblock the current task. That exception creates an immediate capability debt.

Before the body of work is considered fully closed, the agent **MUST** do one of the following:

1. implement Runtime parity, including tests and evidence, so the next equivalent action uses the Runtime; or
2. when parity is blocked by an external dependency or cannot safely fit the current change, create or update a concrete Runtime issue containing reproduction, expected interface, acceptance criteria, and evidence of the fallback.

The fallback **MUST NOT** be silent. Final delivery must identify it as `UNVERIFIED| runtime capability gap` until parity exists. Repeated native fallback for the same untracked gap is a policy violation.

This is the continuous evolution loop:

```text
reason in Hermes
  → execute in Runtime
  → detect capability gap
  → native exception only if required
  → implement or contract Runtime parity
  → next equivalent interaction executes in Runtime
```

### 4. Evidence

Claims of Runtime execution or token savings **MUST** be backed by Runtime output or an evidence reference. Savings without a measured receipt **MUST NOT** be reported.

## Enforcement

- `AGENTS.md#tool-routing` is the operational summary and links to this ADR.
- The bundled `simplicio` plugin should block or warn on native execution when an equivalent Runtime command exists.
- Runtime capability gaps should be deduplicated before issue creation.
- Tests should cover routing, fallback labeling, and capability-debt creation.
- `simplicio-runtime#3195` is the first parity issue created under this decision, covering first-class compact read/search/Git/diff/test execution.

## Consequences

### Positive

- every interaction can expose and close Runtime gaps;
- execution becomes measurable, compactable, reproducible, and evidence-bearing;
- native tools remain available for recovery without becoming permanent bypasses;
- Hermes remains the reasoning layer rather than duplicating the Runtime.

### Costs

- small tasks may pay Runtime process startup until warm execution is universal;
- capability closure can expand a task when a new gap is discovered;
- first-class commands and adapters must be maintained across platforms;
- policy enforcement must distinguish reasoning/coordination from execution.

## Rejected alternatives

1. **Hermes-native execution first:** rejected because it bypasses Runtime economics and prevents capability growth.
2. **Native and Runtime as equal peers:** rejected because gaps remain invisible and routing becomes inconsistent.
3. **Block all native fallback:** rejected because a missing Runtime capability could deadlock delivery.
4. **Create an issue but continue using native tools forever:** rejected because tracking without eventual parity does not evolve the system.
