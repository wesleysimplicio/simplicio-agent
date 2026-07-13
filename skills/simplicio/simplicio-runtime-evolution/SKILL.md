---
name: simplicio-runtime-evolution
description: Evolve the Simplicio Runtime by porting external patterns into runtime modules with deterministic edits, focused tests, and evidence. HARD MANDATE (Wesley 2026-07-08) — BOTH bots (AlfradHD ~/.hermes, Simplicio ~/.simplicio_agent) drive execution through Simplicio Runtime via MCP/CLI, and verified evolution is merged straight into `main` of both repos. Encodes the git-to-main pitfalls (worktree trap, origin/main advanced, stash preservation, MCP quirks) and `doctor --json` gap detection.
---

# Simplicio Runtime Evolution

## Hard mandate (Wesley, 2026-07-08 — durable, first-class)
1. **Both bots execute through Simplicio Runtime via CLI-first, MCP-fallback.** AlfradHD (`~/.hermes/config.yaml`) and Simplicio (`~/.simplicio_agent/config.yaml`) both register `mcp_servers.simplicio` (command `simplicio serve --mcp --stdio`, `supports_parallel_tool_calls: true`). Standing directive (user 2026-07-11): the **`simplicio` CLI is the PRIMARY** execution surface; MCP (`mcp_simplicio_*`) is FALLBACK only (use it when a client already has the server wired and the query is quick). Prefer `simplicio` CLI over `mcp_simplicio_*` and over raw Hermes-native file/terminal edits for any runtime mutation. Verify once with `hermes mcp list` → `simplicio ✓ enabled`.
2. **Evolution lands on `main`, not only a feature branch.** After a change is verified, merge the feature branch into `main` of BOTH repos and push. Feature branches are intermediate; `main` is what ships. Source of truth for skills = `simplicio-agent`; `simplicio-runtime` mirrors under `skills/<cat>/`.

## Opening an architecture backlog (verified recipe)

When the user asks to open issues from an architecture review, treat it as a multi-item delivery, not as a single vague epic. Use the Simplicio CLI as the execution path (`simplicio shell -- gh ...`), while keeping reasoning and decomposition in the agent.

1. Run intake before creating anything: verify GitHub auth, learn repository conventions, and search open issues by the major concepts. Do not duplicate an existing epic or canonical contract issue.
2. Decompose the review into class-level, independently implementable issues. Typical lanes are: canonical task/state contract, actuator/transport boundary, write-set and ownership, doctor/identity health, scheduler backpressure, memory lifecycle, transport-independent IPC, golden-path E2E, and documentation consistency.
3. Every issue body must include: context and observed evidence, objective, proposed design, numbered implementation steps, explicit acceptance-criteria checklist, required evidence, dependencies, and out-of-scope boundaries. Avoid titles that merely restate a symptom.
4. Create independent issues in parallel through `simplicio shell -- gh issue create --body-file ...`; do not serialize unrelated issue creation.
5. Verify each created issue independently (URL, OPEN state, title, and count of acceptance criteria). Then comment on the parent epic/canonical contract with the decomposition links.
6. Report all URLs, existing issues intentionally reused, evidence of creation, and any auth limitation that did not block the operation.

For the detailed issue decomposition template and the cross-repo linking pattern, see `references/architecture-issue-backlog.md`.

## Landing a change on main (verified recipe)
See `references/git-landing-main.md` for the exact command sequence. Summary:
1. Orient + recall (`simplicio map --repo . --for-llm markdown`, `simplicio memory "<q>"`, `simplicio doctor --json`).
2. Make the change deterministically (`simplicio edit --plan plan.json` / `mcp_simplicio_edit`).
3. Verify in-place (`simplicio shell -- python3 -m pytest ...` or skill selftest).
4. Land on main: stash pre-existing work → checkout main → merge feature branch → push (rebase if rejected) → restore stash.

Use this skill when the task is to turn an external pattern, repo idea, or session insight into a concrete change inside `simplicio-runtime` or adjacent Simplicio repos.

## Readiness gap audit before a wave or final delivery
When the user asks whether the ecosystem is updated, ready, or what remains, run a read-only gap audit before changing code or declaring completion. Record each finding as `MEASURED|` or `UNVERIFIED|` and separate these classes:

1. **Runtime health:** version, `simplicio doctor --json`, native bind reachability, policy/evidence state, adapter availability, and missing local models.
2. **Source synchronization:** fetch/prune each affected repository; inspect branch/upstream divergence, generated `.simplicio`/`.orchestrator` artifacts, checkpoint branches, and whether the canonical checkout is on `main`.
3. **Package parity:** query each installed adapter's machine-readable version contract directly (`--version --json` where available), then compare it with the runtime doctor's detected version. A direct package version plus doctor `unknown` is a detector-contract gap, not proof that the package is missing.
4. **PR/CI state:** query every relevant PR for head SHA, merge state, checks, and URL. If jobs fail with zero steps/logs, inspect the human-readable run annotations before blaming the diff; messages such as billing/account lock are infrastructure blockers, not code-test evidence. Keep the PR open and label code behavior `UNVERIFIED|` until local/final tests run.
5. **Backlog:** count open issues per repository and sum with a real command; do not infer completion from merged PRs while issues remain open.
6. **Resource readiness:** measure free disk and identify regenerable `target/`, virtualenv, node_modules, cache, and worktree consumers before launching compiled waves. Never delete automatically during an inventory; classify safe-to-regenerate versus state/evidence that must be preserved.

Use `references/readiness-gap-audit.md` for the compact command matrix and reporting template. This audit is read-only; it does not replace the final test wave, merge gate, or issue close-gate.

## Local release (rebuild binary + reinstall adapters + verify)
When a `git pull` advances the runtime version (e.g. v3.4.0 -> v3.5.0) or you
make local edits that must ship, the installed binary + Python adapters go
stale. Full recipe + pitfall detail in `references/local-release.md`. Summary:
1. Pull all `~/Projetos/ai/*` repos (`git pull --ff-only`).
2. Commit local working-tree changes (run `python3 scripts/audit-script-ownership.py`
   first if the pre-commit gate flags "script ownership inventory stale" — do NOT
   skip the gate; the flagged "secret" lines in the generated inventory are false
   positives = script paths, not creds). Push `main`.
3. `cargo build --release --features rich-repl` (~5min on 8GB mac); `cp` the binary
   to `~/.local/bin/simplicio` AND `/opt/homebrew/bin/simplicio`.
4. Reinstall adapters from their checkouts with **Homebrew Python 3.11**, not
   system `pip3` (which is 3.9.6 and too old):
   `/opt/homebrew/bin/python3.11 -m pip install -e .` for
   `simplicio-mapper`, `simplicio-dev-cli`, `simplicio-loop`.
5. Verify: `simplicio doctor --json` (`overall_status:"ok"`, compatibility
   `compatible`) + `simplicio runtime smoke --json` (`status:"passed"`).

## Checkpoint and restore-point protocol (when the user asks to save current work)
A save request is not automatically a merge request. First preserve the current source state losslessly, then report whether it is merely checkpointed, under PR, or merged.

1. Audit every affected checkout/worktree with `git status --short --branch`, `git diff --stat`, and `git ls-files --others --exclude-standard`.
2. Separate intended source/tests from runtime-generated state. Never stage `.simplicio/*`, `.orchestrator/*`, watcher journals, event ledgers, caches, or build output unless the task explicitly makes those files the deliverable.
3. Create a uniquely timestamped checkpoint branch (never rewrite shared `main`), stage only explicit source/test paths, and verify `git diff --cached --name-only` before committing.
4. Push the branch, then create an annotated restore tag at the checkpoint commit and push the tag. Verify both the remote branch SHA and remote tag resolve to the expected commit.
5. Open a PR when the repository workflow requires it, but do not imply completion or merge unless the acceptance gates have actually passed. A restore point proves preservation, not tests or issue completion.
6. If tests are intentionally deferred, state that explicitly in the PR body and final report; do not fabricate validation. Generated local artifacts may remain uncommitted and should be named as such.

## Adversarial PR repair and safe diagnostic probes
When a review finds a real correctness or AC gap, treat the PR as `FIX-REQUIRED` even if GitHub reports `mergeable`/`CLEAN`. Re-query the live head, base, files, and checks before editing. If the branch contains an unrelated fix already present on `origin/main`, rebuild it from the updated base and cherry-pick only the scoped commit; preserve generated state in a stash rather than committing it.

For `doctor`/health commands, the diagnostic path must be read-only: path resolution must not call `create_dir_all`, open/init is the only owner of database creation, and an existing regular file is not healthy until a read-only SQLite validation succeeds. Review sibling/legacy doctor implementations for hard-coded paths and route them through the canonical resolver. Add environment-selection, invalid-file, side-effect, and reopen/search contract tests to the tree; if execution is deferred by the user, mark those tests `UNVERIFIED|` and keep the PR/issue open.

See `references/checkpoint-restore-points.md` for the compact command/evidence recipe.

## Verify-before-commit gate (refines the "commit on main" mandate)
Wesley's standing mandate: "everything working is the default → commit and push". A later correction sharpened it: **committing without verifying is the antithesis of "working"**. Gate:
1. Build/typecheck/test the touched path for real (`simplicio shell -- python3 -m pytest <slice>`; for TUI: `cd ui-tui && npm run build` and confirm `dist/` emitted with no error).
2. Confirm the changed symbol is still imported/valid where used (grep importers before deleting a body).
3. Only then `git add <explicit files>` → `git commit` → `git push origin main`.
Never `git add -A` / `git add .` — staged scope must be exactly the verified change.

### Protect third-party content (hard rule — user mandate "não exclua nada que não seja seu")
Simplicio runtime commands and the Rust toolchain leave **untracked side-effects in the working tree** that a broad `git add` silently captures and commits as YOUR change:
- `simplicio edit` / `validate` / `advise` / `parallelism` rewrite `.simplicio/memory/seeds.sql`, `.simplicio/cron-state/*`, `.simplicio/events.jsonl`, `.simplicio/history/*`. A `seeds.sql` rewrite can **delete thousands of third-party skill rows** (seen: 1,147 deletions of `.claude/skills/*` from other authors) even though you only edited one Rust file.
- `cargo build` / `cargo test` run `rustfmt` on touched crates, reformatting unrelated `*.rs` files (`behcs.rs`, `hyper_behcs.rs`) you never opened.
- Watcher/hook output and release-monitor state get created as new files.

Concrete prevention + verification (full recipe in `references/commit-scope-containment.md`):
1. After editing, run `git status --short` BEFORE any add. Expect ONLY your intended files.
2. Stage explicitly: `git add <file1> <file2>` (never `-A`, never `.`).
3. Confirm: `git diff --cached --name-only` shows exactly your files.
4. Prove third-party files untouched: `git diff <parent> HEAD -- .simplicio/memory/seeds.sql | wc -l` → must be `0`.
5. If a broad add already committed, do NOT `git reset --soft` (keeps the polluted index). Use `git reset --hard <parent>` to get a clean tree, re-apply ONLY your edits via `simplicio edit --plan`, then stage explicitly and `git push --force-with-lease` to rewrite the bad commit. See the reference.

## Standing rule — never delete/touch files you didn't create (user 2026-07-11)
"Não exclua nada que não seja seu." When landing a change, the working tree may
contain pre-existing modifications by other tooling/bots. These are NOT yours:
- `git status --short` BEFORE any add → separate your files from alien ones.
- Stage explicitly: `git add <file1> <file2>` (never `-A`, never `.`).
- The post-commit `git diff --stat` must show ONLY your intended files.
- If a broad add captured alien files, recover per
  `references/commit-scope-containment.md` (`git reset --hard <parent>` then
  re-apply only your edits).
- Also see `references/git-local-branch-trap.md` for the local-checkout-on-
  stale-feature-branch case (commit lands on `issue/3050`, not `main`) and the
  `simplicio edit` must-pass-`--repo .` pitfall.

## Local-branch trap (verified 2026-07-11)
The `simplicio-runtime` canonical checkout was on branch `issue/3050`, not
`main`. A `git commit` there lands on the wrong branch. Recipe that worked:
`git add <explicit>` → `git commit` (on issue/3050, sha ABC) → `git checkout
main` → `git cherry-pick ABC` → `git push origin main` → `git checkout
issue/3050` (restore, no loss). Always confirm with `git log --oneline -2
origin/main`. Full detail + the `simplicio edit --repo` mis-target pitfall in
`references/git-local-branch-trap.md`.

## Branding decree vs AGENTS.md conflict
When the user demands "no Hermes in the Simplicio Agent face" (e.g. rename `HERMES_CRON_MAX_PARALLEL` → `SIMPLICIO_AGENT_CRON_MAX_PARALLEL`), do NOT blindly strip `HERMES_*`:
- `AGENTS.md` hard-forbids renaming the `HERMES_*` env prefix / internal code ("Internal code stays Hermes").
- Resolution that satisfies both: make the user-facing name canonical (`SIMPLICIO_AGENT_*`) where it is shown (tips, docs, UI), BUT keep `HERMES_*` as a **silent legacy fallback** in the reading code (`os.getenv("SIMPLICIO_AGENT_X") or os.getenv("HERMES_X")`). Update tests to the canonical name. Removes Hermes from the user's view while honoring the repo's internal-stability rule.

## Concurrent multi-bot git conflicts
Two bots (AlfradHD `~/.hermes`, Simplicio `~/.simplicio_agent`) share the same GitHub `main` and can edit the same working tree. Watch for:
- `git push` rejected → remote advanced (other bot landed). Fix: `git pull --rebase origin main` (my commit rebases cleanly if it touched different files), then `git push`.
- **Alien files in MY working tree**: `git status` shows modified files you did NOT touch (e.g. `cli.py`, `hermes_cli/banner.py` from another bot's session). Do NOT `git add` or commit them. Isolate: `git stash push <alien-files> -m "wip-alien-<bot>"`, do your rebase/push, then `git stash pop` to restore them untouched.
- After landing, confirm `git rev-list --left-right --count origin/main...HEAD` reads `0 0`.

## Tool routing for Simplicio work

- Prefer **Hermes-native tools first** for orientation, reading, searching, and decision support.
- Use **Simplicio CLI/MCP next** for execution, deterministic edits, validation, and evidence.
- When the task can be split, keep Hermes in the reasoning/coordination role and hand only the mutation step to Simplicio.
- If the repository already documents a local routing rule in `AGENTS.md`, mirror it in the skill and keep the skill aligned with the repo source of truth.

## Core workflow

1. **Orient on the target repo first**
   - Identify the exact module(s) to change.
   - Prefer a compact repo map or targeted file discovery before broad reads.
   - If a high-level CLI/map command returns truncated or killed output, switch to narrower file inspection and module-level tests rather than repeating the same broad command.

2. **Translate the pattern into a runtime primitive**
   - Ask: is this a persistence primitive, memory tier, handoff, validation gate, decay policy, or stop condition?
   - Map the idea to one runtime-owned abstraction instead of bolting on a one-off script.

3. **Implement deterministically**
   - Keep the change scoped to the owning module.
   - Prefer deterministic edits over manual piecemeal rewrites.
   - When a stub becomes real behavior, update the code and the schema together.

4. **Convert stub tests into behavior tests**
   - Replace "stub must fail" assertions with real outcome checks.
   - Add round-trip tests for persisted data, idempotence, and state transitions.
   - Verify the new behavior with the smallest possible test slice first.

5. **Verify in layers**
   - Run focused tests for the touched module.
   - Only widen to the workspace when the local slice is green.
   - If the workspace has unrelated failures, report them separately and do not let them obscure the targeted evidence.

6. **Close with evidence**
   - Capture the exact test result or command output that proves the runtime change works.
   - Do not claim completion until the changed path has been exercised.

## Asolaria-to-runtime mapping heuristics

- **Workspace / project / session rows** → durable identity and scope management.
- **Observations** → event capture for session lifecycle and tool activity.
- **Handoffs** → cross-agent continuity and next-step snapshots.
- **Tiered memory** → working / episodic / semantic / procedural retention.
- **Decay / purge** → retention control and cleanup policies.
- **FTS / embeddings** → retrieval and ranking, not just storage.

## Measurement & Token-Tracking gaps (to evolve)

Identified in the 2026-07-08 snake-game session. The runtime currently has no first-class token measurement or cost-tracking for LLM-driven tasks — the only surface is the savings ledger (which tracks runtime-side savings, not total LLM spend).

### Gap 1: No native token tracker
- **Request:** `simplicio measure tokens` — read the most recent Hermes prompt/output, estimate tokens via tiktoken, and return structured `{input, output, total, model, cost_estimate}`.
- **Why:** Without this, every deliverable that needs cost reporting falls back to manual estimation (UNVERIFIED|).
- **Value:** closes the loop for `simplicio savings` to account for total spend, not just saved.

### Gap 2: Savings ledger doesn't bridge to LLM spend
- **Request:** `simplicio savings record --input-chars N --output-chars N --model X` (from tool-call hooks) so the savings ledger can produce a total-cost-of-session alongside tokens-saved.
- **Why:** Current ledger has 0 events for LLM-heavy sessions — it only counts runtime-side savings (deterministic edit, etc.).

### Gap 3: No `simplicio measure` MCP tool
- **Request:** Expose `mcp_simplicio_measure` so agents can call token/cost measurement programmatically from within Hermes.
- **Why:** MCP tools are the first-class bridge; agents shouldn't need to drop to CLI for measurement.

### Gap 4: No HTML report template
- **Request:** `simplicio report generate --type task-report --output report.html` — auto-generate an HTML report from the session's savings + evidence ledgers.
- **What it should contain:** summary cards, metadata, step-by-step, token breakdown, cost, evidence chain, feature checklist, gaps.
- **Why:** Every "build + measure" session today hand-writes the same report pattern manually. A single command saves 1-2s and eliminates estimation variance.

### Gap 5: Savings report confidence
- The 2026-07-08 session returned `Baseline kind: estimated`, `Confidence: low`, `Tokens saved: 0` for a snake game that cost ~US$0.0036. The ledger has no hooks for LLM-side events — it only tracks runtime optimisations. Bridge this (Gap 2) and the confidence goes from low/high.

## Pitfalls

- Do not leave legacy stub assertions behind after the implementation lands.
- Do not stop at schema creation; add the write/read path and at least one round-trip test.
- Do not repeat the same broad failing command unchanged; narrow the target and change strategy.
- Do not treat unrelated workspace failures as proof that the module change failed.
- Do not full-merge remote bot branches when `main` has commits the branch lacks — cherry-pick or close as already absorbed (#2976-style empty picks).
- Do not let `git add -A` / `git add .` capture runtime side-effects (seeds.sql rewrites, rustfmt churn, cron-state) as your change — they delete or modify third-party content. Stage explicitly and verify with `git diff <parent> HEAD -- <sensitive-file>` = 0 lines. Recovery recipe in `references/commit-scope-containment.md`.

## Support files

- `references/store_ops_consolidation.md` — session-specific implementation notes and test evidence for the Asolaria `store_ops` consolidation.
- `references/git-landing-main.md` — exact, verified command sequence for landing evolution on `main` of both repos, including the worktree trap, origin/main rebase, stash-preservation, alien-working-tree isolation, and `doctor --json` gap detection.
- `references/local-release.md` — full local-release recipe: rebuild the Rust binary, reinstall Python adapters with Homebrew Python 3.11, pre-commit inventory-gate fix, and `doctor`/`runtime smoke` evidence bar.
- `references/remote-branch-triage-and-sync.md` — lossless `main` sync, audit other bots' remote branches, cherry-pick with skip-empty, wormhole release smoke, prompt version-matrix diagnosis, delete stale remote refs.
- `references/commit-scope-containment.md` — how `git add -A` silently captures runtime side-effects (seeds.sql third-party deletions, rustfmt churn) and the recovery recipe via `git reset --hard` + explicit re-stage + `push --force-with-lease`.
- `references/roundtrip-logic-validation.md` — validate byte<->symbol / encode<->decode codec logic in Python first (instant iteration) before transplanting to Rust; covers the glyph_genesis short-group endianness bug.
- `references/git-local-branch-trap.md` — local checkout on a stale feature branch (`issue/3050` not `main`) → cherry-pick to main recipe, plus the `simplicio edit` must-pass-`--repo .` mis-target pitfall, plus the "never delete others' files" standing rule.
