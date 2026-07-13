---
name: large-task-decomposition
description: Decompose massive tasks into parallel independent workstreams dispatched via background subagents, with conflict-aware merging and final verification.
---

# Large Task Decomposition

Use when the task is too big for a single linear pass — 5+ subtasks, 50+ files, or work that can run independently. The user insists on maximum parallelism: "Utilize vários agents em background." Do not serialize independent work; batch it.

## Core Principle

**Break the work into self-contained slices, dispatch them in parallel via `delegate_task(background=true)`, let them all run, then merge and verify at the end.**

Each slice must:
- Be fully independent (no two agents editing the same file at the same time, or if they must, document the conflict)
- Have a clear success criterion (e.g., "cargo check passes" or "the file compiles")
- Report its results in a structured summary

## Workflow

### Phase 1: Analysis (single agent)

Before dispatching anything, understand the scope:

```
1. Identify all independent work items
2. For each item: what files will be touched, what's the goal, how to verify
3. Assign one agent per item
```

### Phase 2: Dispatch in Parallel

```python
# Pseudocode pattern
for item in work_items:
    delegate_task(
        goal=item.goal,
        context=item.context,
        toolsets=item.toolsets,
        background=True  # CRITICAL: runs async, doesn't block
    )
```

Key parameters:
- `background=true` — runs asynchronously; you and the user keep working while agents run
- Each agent gets its own terminal + file system context
- Max 32 concurrent children per user; if you hit limits, batch in waves

### Phase 3: Collect Results

Background agents re-enter the conversation as `[ASYNC DELEGATION COMPLETE]` messages. Each result includes:
- What was done
- Files modified
- Verification result (cargo check / test pass)
- Any issues encountered

Do NOT poll or wait. Just continue working on other things; results come to you.

### Status language discipline (critical)

When the user asks variants of **"fez?" / "terminou?" / "commit?"** while background agents are still running:

- **Dispatch is not completion.** Saying "I dispatched 20 agents" does **not** mean the work is done.
- Do **not** say commit/push/PR/release happened unless you personally verified the side effect.
- Report the state in one of these buckets only:
  - **planned**
  - **dispatched / in progress**
  - **integrated locally**
  - **validated**
  - **committed**
  - **pushed**
  - **PR opened / merged / released**
- If async work has not returned yet, say exactly that and stop short of stronger claims.

This user is highly sensitive to overclaiming. A truthful "not finished yet" is mandatory whenever integration or validation has not actually occurred.

### Multi-repo umbrella tasks

When the request spans MANY repositories at once (for example "optimize all repos under a parent directory"):

1. **Inventory first** — list repos, branches, and dirty/clean state before dispatching agents.
2. **Separate execution from research** — dedicate some agents to code changes and some to extracting transferable patterns from the reference source.
3. **Preserve dirty repos** — do not reset or overwrite existing local work; agent prompts must explicitly say this.
4. **Integrate repo-by-repo** after results return; never treat a cross-repo batch as green until each repo has its own verification result.
5. **If the user says "all repos" / "don't forget any" / "todos os projetos"**, convert the inventory into a concrete coverage checklist with the exact repo names, surface that list back to the user, and dispatch at least one worker per listed repo (or explicitly record why a repo was skipped).
6. **Status reporting must stay per repo** — track each repository as planned, dispatched, integrated locally, validated, committed, pushed, PR opened/merged, or released. Never collapse mixed states into a blanket claim like "done for all repos".

This reduces accidental conflict and prevents false "everything optimized" claims.

### Phase 4: Merge & Verify

After ALL agents complete:

1. **Check git status** — `git status --short` to see uncommitted changes
2. **Run final cargo check** — some agents may have conflicted modifications to the same file; cargo check catches these
3. **Resolve conflicts** — if multiple agents edited the same file, manually merge the changes
4. **Commit and push** — use a comprehensive commit message listing every work item
5. **Open PR** (if branch protection is active) — create a feature branch and PR

### Phase 5: Report

Give the user a concise summary table:

| # | Task | Status | Details |
|---|---|---|---|
| 1 | main.rs extraction | ✅ | −24K lines |
| 2 | Rename real_* | ✅ | 15 files renamed |
| ... | ... | ... | ... |

## Conflict Management

When multiple agents modify the SAME file (inevitable with main.rs in a Rust project):

| Conflict Pattern | Symptom | Resolution |
|---|---|---|
| Two agents add `mod X;` at different lines | Both lines coexist, but may be out of order | Sort mod declarations alphabetically in merge |
| One agent extracts dispatch, another adds dispatch arm | Dispatch arm references function that no longer exists in main.rs | Point arm to the new module path |
| Dead code agent removes `#![allow(dead_code)]`, another agent's code triggers it | Build error about dead code | Add targeted `#[allow(dead_code)]` on the specific item, not file-wide |

**General strategy:**
1. The first agent to finish may make changes that break a later agent's patches
2. Run `cargo check` AFTER all agents complete — don't trust individual agent verifications when they ran concurrently
3. Fix compilation errors one by one, starting with the most fundamental (duplicate symbols, missing modules)

## User Preferences (this user)

- **"Utilize vários agents em background"** — default to maximum parallelism. Batch ALL independent work items at once.
- **"Roda cargo no final"** — always run a final cargo check after merging all parallel results
- **"Subir para main"** — commit, push, and create PR when done; don't leave work uncommitted
- Prefers comprehensive action over incremental ("Resolva tudo!")

## Pitfalls

1. **Two agents modifying the same file simultaneously is the #1 source of merge pain.** When possible, structure tasks so each agent owns different files. When impossible, document the expected conflicts and be ready to manually merge.

2. **Cargo check timeouts.** A large Rust project can take 5+ minutes to compile. Use `background=true` with long timeouts (600s+) and rely on the async notification.

3. **Git renames may not be detected if agents concurrently create and delete files.** Use `git mv` for renames; check `git status` shows them as renames (R), not delete+add.

4. **Don't dispatch more agents than the user's configured max_concurrent_children** (default 32). If you have more work items, batch them.

5. **Always run cargo check at the end even if every individual agent passed.** Concurrent edits to shared files can create conflicts that only surface when all changes are combined.

## Related Skills

- `thermo-nuclear-code-quality-review` — use for the code quality audit that identifies what needs refactoring
- The review skill's `references/safe-module-extraction.md` — the actual Rust extraction technique
- `rust-monorepo-refactoring` — post-extraction visibility and module path fixes
