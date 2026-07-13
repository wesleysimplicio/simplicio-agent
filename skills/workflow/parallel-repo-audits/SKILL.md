---
name: parallel-repo-audits
description: Audit many local git repos in parallel, consolidate implementation opportunities, and defer shipping work until the audit is complete.
---

# Parallel Repo Audits

Use when the user asks to inspect or compare **multiple repositories** before implementing, committing, releasing, or packaging changes.

Typical triggers:
- "veja o que podemos acrescentar em todos os projetos"
- "audite todos os repos em ~/Projetos/..."
- "antes de fazer PR/release, veja onde isso cabe no ecossistema"
- cross-repo absorption of ideas/patterns from another codebase

## Core rule

**Do the audit first, then ship.**
If the user explicitly asks for a cross-repo audit before commit / PR / merge / release / package publishing, do **not** jump ahead to shipping steps.

## Default execution pattern

### 1. Enumerate the real repos first
Verify the actual git repos on disk. For each repo, capture at minimum:
- path
- current branch
- dirty/clean status
- remote

This prevents auditing non-repos, generated directories, or stale assumptions.

### 2. Default fan-out = 6 agents
For broad repo surveys, use **exactly 6 parallel agents by default** unless the user explicitly asks for a different count.

Partition the repo set across those 6 agents in sensible slices, for example:
- agent 1: core runtime repos
- agent 2: CLI/tooling repos
- agent 3: loop/orchestration repos
- agent 4: packaging/distribution repos
- agent 5: mapping/observability repos
- agent 6: marketing/docs/product surface repos

The user prefers this as a standard operating mode.

### 3. Give each agent a strict output shape
Each subagent should return, **per repo**:
- recommendation
- target files / modules
- expected benefit
- effort
- risk
- evidence

That structure makes consolidation fast and avoids vague research summaries.

### 4. Consolidate before implementation
After all audit slices return:
- merge overlapping recommendations
- rank by impact / effort / risk
- separate "worth doing now" from "not worth it"
- only then decide what to implement before PR / release / package publishing

## Recommended audit lenses

When importing patterns from another project or author, repeatedly check these classes of reuse:

### Cross-repo absorption synthesis (important)

When the user asks for a **final cross-repo synthesis** such as "what already exists / what other agents are applying / what still lacks to honestly say we absorbed the best", do not stop at a list of matches.

For **each repo**, classify findings into exactly these buckets:
- **already exists** — explicit implementation or contract in the repo
- **in progress** — active diff / branch / generated artifact / local changes clearly moving the pattern forward
- **still missing** — only docs/research/intent exist, or no evidence found

The final answer should be honesty-first and decision-ready: say which repos are truly ahead, which only contain plans, and which merely have adjacent concepts.

### Evidence discipline for pattern-absorption audits

Do not overcount **generic term matches** as proof of absorption. Words like `watcher`, `handoff`, `CANON`, `verify`, or `orchestrator` often appear for unrelated reasons.

Treat as **strong evidence** only when one of these is present:
- explicit source attribution (`Asolaria`, `JesseBrown1980`, `ai-memory`, `HRM`, etc.)
- a source/target contract or schema that names the absorbed pattern
- a README / GOAL_RESULT / changelog entry stating the absorption
- concrete source files implementing the pattern with matching semantics

Treat as **weak evidence** unless confirmed by reading the file:
- bare grep hits on generic vocabulary
- packaging/docs mirrors of claims not backed by runtime code
- unrelated uses of words like `watcher`, `canonical`, `handoff`, `verify`

### Packaging vs runtime distinction

In ecosystem audits, explicitly separate:
- **runtime/source repos** — where the pattern truly lives
- **packaging/distribution repos** — where the pattern may only be surfaced, documented, or shipped
- **fork/sync repos** — where generic upstream features may resemble the target pattern without actually absorbing it

A public packaging repo with a skill, README mention, or install flow is **not** equivalent to the runtime having operational parity. Say so clearly.

1. **Persistent handoff / memory / wiki**
   - cross-session handoff
   - cross-agent continuity
   - resumable work state

2. **Hierarchical planning / phase control**
   - phase planner
   - tactical guards
   - explicit escalate / explore / implement modes

3. **Watcher / claims / verification gates**
   - independent verification before claiming success
   - evidence-first completion criteria
   - honest MEASURED / CANON / UNVERIFIED-style reporting

4. **Halt / state-machine discipline**
   - stop reasons
   - budget / cap / lock / latch semantics
   - resumable incomplete exits

5. **Operator UX for long-running/background work**
   - status surfaces
   - resume commands
   - handoff artifacts
   - background-loop observability

## Output contract for the controller

The final controller summary should be concise and decision-ready. Prefer a table per repo:

| Repo | Recommendation | Target files | Effort | Risk | Priority |
|---|---|---|---|---|---|

Then add:
- global top 3 priorities
- quick wins
- items to reject explicitly

## Pitfalls

- Do **not** start commit / push / PR / merge / release work before the requested cross-repo audit is finished.
- Do **not** assume every repo should absorb every pattern; explicitly say when a pattern is a bad fit.
- Do **not** audit from repo names alone — verify branch, dirty state, and actual files first.
- Do **not** let subagents return essay-length prose without target files and evidence.
- For public packaging repos, avoid recommendations that would expose private runtime/source internals.

## Repo-script execution pitfall

When reviewing loop/hook systems that spawn sibling scripts, verify how the script resolves the repo root.
A common safe pattern in testable hook systems is:
- prefer the runtime working directory when the hook is executed inside a temporary repo fixture
- avoid hard-wiring only the hook file's own source directory if the hook must operate on the caller's repo state

This matters in end-to-end tests where the hook binary lives in one checkout but the simulated repo state lives in a temporary working directory.

## Verification before shipping

Once the audit is complete and implementation starts, only ship after:
- repo-specific tests/checks pass
- dirty-state/conflict review is complete
- final commit/PR/release work reflects the audit priorities rather than bypassing them
