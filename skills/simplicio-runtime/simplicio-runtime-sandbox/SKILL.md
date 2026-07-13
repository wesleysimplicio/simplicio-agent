---
name: simplicio-runtime-sandbox
description: Simplicio Runtime file-write sandboxing — the MCP surface is sandboxed (#2674) but the CLI is not. When to use which, how to write files outside the repo, and the verify-before-claiming discipline for runtime internals.
triggers:
  - need to create/edit a file via Simplicio runtime
  - target path is outside the current repo/workspace root (~, /tmp, sibling dir, Desktop)
  - about to state a definitive claim about runtime behavior, limits, or "gaps"
  - user pushed back on a runtime claim ("ajuste isso", "tem certeza?", "verifica")
---

# Simplicio Runtime — Edit/Read Sandbox (MCP vs CLI)

## Core fact (MEASURED| — verified against source + live test, 2026-07)

The Simplicio `edit`/`read` workspace sandbox is **NOT uniform across surfaces**:

| Surface | Writes outside workspace root? | Evidence |
|---|---|---|
| **MCP** (`mcp_simplicio_simplicio_edit`, `mcp_simplicio_simplicio_file_read`, `mcp_simplicio_simplicio_read`) | ❌ BLOCKED | Error: `simplicio_edit: sandbox — file "<path>" escapes the workspace root "<root>"`. Source: `src/main_parts/chunk_08.rs:4165` (`mcp_edit_sandbox`, issue **#2674**). |
| **CLI direct** (`simplicio edit ...` in terminal) | ✅ WRITES ANYWHERE | Live test: `simplicio edit '{"file":"/tmp/x.txt","operations":[{"op":"create","text":"..."}]}' --json` → `status: ok`, `created: true`. No sandbox check in the CLI edit path. |

### Why
- `mcp_edit_sandbox(repo, plan)` (`chunk_08.rs:4139`) normalizes the target path and rejects if it does not `starts_with` the repo root. Invoked ONLY from the MCP tool dispatch (`"simplicio_edit" =>` line 3946) and the read counterpart `mcp_read_sandbox` (line 4173, used by `simplicio_file_read` / `simplicio_read`).
- The CLI `edit` command (`RemediationExecutor::apply_plan`, `anti_fake_remediation.rs:483`) does `repo_root.join(plan.file)` and writes — **no escape check**. An absolute path outside the repo is honored.

## Decision rule — which surface to use
- **File inside repo** → either MCP or CLI works. MCP preferred (token-saving + evidence ledger).
- **File OUTSIDE repo** (want it in `~`, `/tmp`, Desktop, a sibling) → use the **CLI directly in the terminal**, NOT the MCP tool. The MCP tool errors out.
- Do NOT describe this as "the runtime can't write outside the repo" — that is imprecise. Say: **"the MCP surface is sandboxed (#2674); the CLI is not."**

## Pitfall — verify runtime claims before asserting (this session's correction)
I stated "gap real do runtime: não escreve fora do repo" from a single blocked MCP call. Imprecise — the CLI writes fine. User said "ajuste isso."

**Rule (re-encoded from AGENTS.md):** Before stating a definitive claim about runtime internals/limits, **verify it** — read the source (`search_files` for the error string / symbol in `simplicio-runtime/src`) OR run a live test. Then label the claim `MEASURED|` (with evidence ref) or `UNVERIFIED|`. Never generalize from one failed call.

## Verification recipe (reproducible)
```bash
# 1) MCP blocks outside-repo (expect sandbox error)
mcp_simplicio_simplicio_edit '{"file":"/tmp/test.txt","operations":[{"op":"create","text":"x"}]}'
# 2) CLI writes outside-repo (expect status:ok, created:true)
simplicio edit '{"file":"/tmp/test.txt","operations":[{"op":"create","text":"x"}]}' --json
# 3) Locate the sandbox source
search_files pattern="escapes the workspace root" path=<simplicio-runtime-repo>
# 4) Clean up test artifacts
rm -f /tmp/test.txt
```

## Related
- Honesty rule in `AGENTS.md` (Simplicio runtime): claims must be `MEASURED|`/`UNVERIFIED|`; never fabricate. Same discipline applies to claims about the runtime itself.
- For creating files inside the repo via runtime, prefer `simplicio edit` with `{"op":"create","text":"..."}` (zero-LLM-token mechanical write).

## References
- `references/sandbox-facts.md` — full code excerpts + live test transcripts.
