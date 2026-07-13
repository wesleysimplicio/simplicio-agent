---
name: simplicio-runtime-asolaria-porting
description: Port Asolaria patterns into Simplicio Runtime as deterministic, testable primitives rather than LLM stubs.
---

# Simplicio Runtime + Asolaria Porting

Use this skill when evolving `simplicio-runtime` by absorbing useful Asolaria ideas: memory tiers, session synthesis, hook gates, handoffs, decay/cleanup, and agent-state plumbing.

## Core principle

Prefer **deterministic runtime primitives** over vague LLM assistance.

When a pattern can be expressed as:
- pure transform,
- explicit redaction,
- bounded summary,
- typed persistence,
- or a gate with a clear verdict,

implement that first. Reserve LLM usage for the edge, not the core.

## When to apply

- You find a `TODO`, `stub`, `unimplemented`, or placeholder in `src/asolaria/*` or adjacent runtime modules.
- The task is to port an Asolaria concept into Simplicio without weakening gates.
- A summary/synthesis step can be made deterministic.
- Privacy, redaction, or session shaping is currently a no-op.
- The runtime needs better evidence, decay, or handoff behavior.

## Default workflow

1. **Orient first** on the target module and its tests.
2. **Prefer the simplest deterministic implementation** that preserves semantics.
3. **Add or tighten tests immediately** for the exact behavior you changed.
4. **Run the narrowest useful test command** for the touched area.
5. **Expand only if the targeted tests pass** and the design still needs more coverage.
6. **Keep gates explicit**: redact, verify, then synthesize or persist.

## Patterns worth porting

### 1) Sanitizer / redaction
- Use real regex-based redaction, not placeholder counters.
- Track how much was redacted.
- Apply a hard body-length limit after redaction.
- Treat sanitizer output as a typed value, not an ad hoc string rewrite.

### 2) Session synthesis
- Prefer deterministic markdown summaries when the desired result is structural.
- Surface counts, first/last signal, and a small highlight set.
- Make summaries stable and testable before considering LLM-based enrichment.

### 3) Hookwall / pre-gates
- Keep the pre-hook gate small and opinionated.
- Reject or redact before the payload reaches the expensive path.
- Verdicts should be explicit and easy to assert in tests.

### 4) Memory / decay / cleanup
- Use typed persistence boundaries.
- Make soft-delete, hard-delete, and purge semantics distinct.
- When cleanup changes behavior, add regression tests around data loss and retention.

### 5) Handoff / session bookkeeping
- Encode ownership transitions explicitly.
- Make accepted handoffs idempotent where possible.
- Use tests that model both happy-path and repeated invocation.

## Pitfalls

- Do not replace a stub with another stub-like abstraction.
- Do not introduce LLM synthesis where a deterministic summary is enough.
- Do not weaken privacy by postponing redaction until after formatting.
- Do not ship a cleanup or purge path without regression tests.
- Do not change semantics in a broad file without verifying the touched branch directly.
- Do not use `write_file`/`patch` on a managed repo (`simplicio-agent`); route through `simplicio edit --plan` or the call is blocked by the plugin.
- Do not use `content` as the operation field in a `simplicio edit` plan — it must be `text`, or the create/replace silently no-ops (validates, applies 0 ops).

## Verification standard

For each ported pattern:
- Add a targeted unit test.
- Verify the new behavior with the narrowest relevant cargo test.
- Keep assertions on concrete outputs: counts, redacted tokens, summary fields, or state transitions.
- If the change affects runtime behavior beyond the unit under test, follow up with a broader integration test.

## Managed repositories & the `simplicio edit` workflow

`simplicio-runtime` AND `simplicio-agent` are **managed by the Simplicio
plugin**: native Hermes `write_file` / `patch` are BLOCKED there (return a
sandbox block). Route through `simplicio edit --plan` or the call is refused.

### v3.5.0 plan schema — EXACT contract (cost 3 failed attempts to close this session)

The canonical binary on PATH is `/opt/homebrew/bin/simplicio` = **v3.5.0**.
Accepted plan shape:

```json
{"file":"src/asolaria/reader.rs","operations":[{"op":"replace","find":"EXACT","with":"NEW"}]}
```

Confirmed-by-live-failure pitfalls:
- `{"operations":[{"file":"...","op":"replace",...}]}` (file INSIDE each op) →
  **FAILS**: `edit plan must specify a target file`. Wrong shape.
- `{"file":"...","operations":[{"op":"replace","find":"...","with":"..."}]}` →
  **WORKS**. `file` at ROOT, `operations` is an array of ops.
- `op: "create"` / `op: "append"` need `"text":"..."` (full content / appended).
- `op: "replace"` uses `find`/`with` (NOT `old`/`new`). Exact string, no regex.
- `--dry-run` prints PASS via watcher but does NOT echo the op diff to stdout;
  trust the apply + `git diff` afterward.
- Version trap: `/Users/wesleysimplicio/.local/bin/simplicio` is **v3.4.0** and
  parses a DIFFERENT shape. Use the PATH binary (v3.5.0) unless you mean the
  older one. Check `which simplicio` + `simplicio --version` first if unsure.

Workflow for a managed repo:
1. Build plan JSON (shape above). `text` is the field for create/append, NOT
   `content` (a plan using `content` validates but applies zero operations).
2. Apply via CLI (accepts a file path):
   `simplicio edit --plan /tmp/plan.json --repo /Users/wesleysimplicio/Projetos/ai/simplicio-runtime`
3. Or via MCP `mcp_simplicio_simplicio_edit` — expects the plan **inline as a
   JSON string**, not a file path. Passing a path yields
   `expected value at line 1 column 1`.

The `simplicio validate` watcher runs automatically after each edit and reports
`targeted-unit-tests` / `syntax-format-and-changed-files`.

### Other tool quirks observed
- `mcp_simplicio_simplicio_exec` blocks shell metacharacters (pipes, `>`). Run
  pipelines in a real `terminal` call, not through the exec MCP.
- `simplicio skills --json` returns an empty list when run outside a runtime
  repo; run it from inside `simplicio-runtime` to enumerate skills.

## Massive parallel fan-out (Wesley: "força total, vários agents Tokio")

When the task is "extract the best from external repos and integrate for real",
do NOT serialize. Clone + fan-out:

1. **Clone candidate repos** (depth-1 to save time):
   ```bash
   mkdir -p ../jesse-imports && cd ../jesse-imports
   for r in asolaria-hbi-hbp asolaria-federation-1024 ai-memory asolaria-agent-memory \
            asolaria-asi-os asolaria-os N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED \
            HRM HYPER-BECHS--the-third-set shannon; do
     gh repo clone JesseBrown1980/$r $r -- --depth 1
   done
   ```
2. **Dispatch analyst agents in ONE batch** (delegate_task `tasks:[...]`, up to
   32 leaf agents). Each: inspect a repo, identify REAL portable code (Rust/
   Python, not fiction), compare to the target runtime module, return a
   structured portability report (<300 words, Portuguese). Give exact target
   file path so reports are actionable.
3. **Dispatch implementer agents in a SECOND batch** (after analysts return) —
   each edits a runtime module via `simplicio edit --plan` (deterministic, 0
   LLM tokens on file bodies). They must compile + `cargo test --lib <mod>`.
4. **Consolidate**: apply the highest-value ports, run module test suite,
   commit + push main (mandate: land on main, zero questions).
5. **Don't duplicate**: first run `simplicio runtime map` + `grep` the runtime
   to confirm what is ALREADY wired (e.g. HBI/HBP `verify_chain` and
   `asolaria_hbi_hbp::ReceiptChain` are already re-exported in `src/asolaria`;
   ai-memory base types already mirrored). Port what ADDS capacity, not what
   already exists.

See `references/fanout-asolaria-port.md` for the exact clone list + agent
context templates used in the 2026-07-09 sprint (13→15 parallel agents).

The `simplicio validate` watcher runs automatically after each edit and reports
`targeted-unit-tests` / `syntax-format-and-changed-files`.

### Other tool quirks observed
- `mcp_simplicio_simplicio_exec` blocks shell metacharacters (pipes, `>`). Run
  pipelines in a real `terminal` call, not through the exec MCP.
- `simplicio skills --json` returns an empty list when run outside a runtime repo;
  run it from inside `simplicio-runtime` to enumerate skills.

## Shipped port: the `asolaria-patterns` skill

The four deterministic primitives below already exist as a packaged skill
(`asolaria-patterns`, in `~/.simplicio_agent/skills/`). Reuse it instead of
re-deriving:

- `nest_cosign` — depth-3 corrective gate + consent roll-up (tamper caught at R.1.2.0).
- `hierarchical_planner` — HRM two-level (high/low) loop, deterministic.
- `behcs_supervisor` — federated supervisor cube/register/GC, deterministic.
- `wormhole_bridge` — alterity envelope + receipt chain (tamper rejected).

Wrapper `simplicio-asolaria` (in `~/.local/bin`) runs all four `--selftest`s plus
pytest. Evidence: 11/11 pytest PASS.

## References

- `references/asolaria-porting-notes.md` — session-derived notes and concrete examples from the latest porting pass.
- `references/fanout-asolaria-port.md` — exact clone list, agent context templates, advisory-lock recipe, and pre-existing-test check used in the 2026-07-09 massive-parallel sprint.
