# INTEGRATION.md — `agent/registry` (lazy_schema + skill_meta)

Ported from `wesleysimplicio/hermes-turbo-agent` (commit `5dad551d5`,
"feat(registry): add on-demand tool schema and skill metadata loading",
issue #98) per `docs/architecture/ADR-0007-turbo-speed-modules-divergence.md`.

## What this module is

A **self-contained, stdlib-only** lazy-loading registry. It keeps only a
`(name, description)` stub (tool) or `SkillManifest` (skill) in memory at
startup, and fetches the full JSON schema / SKILL.md body on the first
`load_*` call, caching it. This is the turbo fork's "lazy JSON schema loading"
axis (MODIFICATIONS.md §6.1, `agent/registry/` #98: 0.07–0.50× payload win).

- `agent/registry/lazy_schema.py` — `LazyToolRegistry`, `ToolStub`,
  module-level `register_tool` / `list_tools` / `load_schema`.
- `agent/registry/skill_meta.py` — `SkillRegistry`, `SkillManifest`,
  `register_skill` / `list_skills` / `load_skill_body` (+ `register_path`).

## Narrow-waist compliance (AGENTS.md)

This module is **edge-only**: it is a registry primitive, NOT a new core model
tool. It does **not** add any tool to the model-tool schema sent per API call,
it does **not** mutate `model_tools.py` / `tools/registry.py`, and it does
**not** touch the system prompt or the tool list sent to the model. It reduces
*payload at the application layer* (deferring full schema construction) while
leaving the per-conversation prompt-cache prefix untouched. Consistent with
ADR-0007 §Consequences: lazy-schema "touch the model-tool schema, which
AGENTS.md guards as the narrow waist — keep them as edges (CLI/daemon prewarm),
not core surface."

## Integration status: STANDALONE — no shared-file edits

Per the port rubric ("if ambiguous/conflict-prone, do NOT edit the shared file
— only create module + INTEGRATION.md; priority: do not break the build"), this
PR ships the module without modifying `run_agent.py`, `hermes_cli/daemon.py`, or
`gateway/run.py`. The module is importable and tested, ready to be adopted by a
follow-up that wires it into the daemon prewarm path.

### Recommended (future) edge hook — daemon prewarm only

`hermes_cli/daemon.py` already exposes a prewarm table
(`PROFILES`, `_preload_tool_registry`, `_preload_skill_index` at lines 71–167).
A non-invasive follow-up can register a prewarm step that calls
`agent.registry.register_tool(...)` / `register_skill(...)` to populate the lazy
registries at daemon warm time. This keeps the work at the edge (daemon), never
in the per-call model-tool hot path, and preserves prompt-cache integrity.

Sketch (do NOT apply in this PR — documented for the follow-up):

```python
# in hermes_cli/daemon.py, inside the desktop/car prewarm set
def _prewarm_lazy_registry() -> dict[str, Any]:
    from agent.registry import register_tool, register_skill
    # populate stubs from ToolRegistry / skills tree here; bodies/schemas
    # load lazily on first load_* call. Does not run load_* at warm time.
    return {"ok": True}
```

### Why no wiring into `run_agent.py` / `gateway/run.py`

Those paths assemble the model-tool schema sent every call. Introducing lazy
schema substitution there risks (a) changing the tool list mid-conversation and
invalidating the sacred per-conversation prompt cache, and (b) rebuilding the
system prompt. Both violate AGENTS.md. The module therefore ships disabled-by-
default at the call layer; adoption happens only through the daemon edge.

## Tests

`tests/registry/test_lazy_schema.py` (7 cases) + `tests/registry/test_skill_meta.py`
(5 cases) = 12 passing. Run with:

```bash
cd <worktree> && python -m pytest tests/registry -o addopts=""
```

These are real unit tests (no mocks): they assert stub-stays-small-until-load,
loader-invoked-exactly-once, cache hit identity, validation errors, and
default-registry helpers. Per AGENTS.md rubric they are unit-level (fast,
stdlib); E2E against temp `HERMES_HOME` belongs to the follow-up that actually
plugs the registries into a warm/cold run.

## Risks to reconcile (for the adopting follow-up)

1. **Source drift** — turbo's `agent/registry/` was removed in a later cleanup
   (commit `c8af8799f`, MODIFICATIONS.md §6.1). This port pins the last-good
   revision `5dad551d5`. Any future re-sync from turbo must re-pull from that
   commit, not `main`.
2. **Naming contract** — internal names (`LazyToolRegistry`, `ToolStub`,
   `SkillManifest`, `register_tool`, ...) are kept verbatim per AGENTS.md
   "never rename internals". Do not rename when wiring in.
3. **`HERMES_*` env prefix** — unaffected; module uses no env vars.
4. **Daemon coupling** — the recommended hook depends only on the public
   `register_*` functions; no change to daemon internals required.
