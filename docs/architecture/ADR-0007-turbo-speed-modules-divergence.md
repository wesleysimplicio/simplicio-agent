# ADR-0007: Turbo speed modules — actual state in Simplicio Agent (CORRECTED)

**Status:** Superseded by verification (2026-07-12). Original 2026-07-11
version was **factually wrong** — it claimed the 6 Turbo speed modules were
never present in `simplicio-agent`. A real `git`-level audit (not just
subagent self-report) on 2026-07-12 disproved that. This corrected version
replaces it.

**Date:** 2026-07-12 (correction).
**Owner:** @wesleysimplicio.
**Related:** `MODIFICATIONS.md` in `wesleysimplicio/hermes-turbo-agent`; AGENTS.md
claim "Simplicio Agent = Hermes Turbo Agent + Simplicio Runtime".

## Why the first version was wrong

The 2026-07-11 audit ran `git log --all` without a prior `git fetch` and
against the wrong paths, concluding the modules were "never present". On
2026-07-12 a `git fetch` + `git cat-file -e origin/main:<path>` check showed
the opposite: 3 of the 6 modules were already merged long ago in commit
`37c84302e` ("perf: port hermes-turbo performance modules as additive
capabilities"). **Lesson (REGRA DA VERDADE): never assert "doesn't exist"
without `git fetch` + `git cat-file` / `git ls-files` on the real remote.**

## Turbo speed/observability axes (issues #81–#103, MODIFICATIONS.md §2)

1. `hermes_cli/daemon.py` — warm daemon → **present** in simplicio (always was).
2. `agent/router/deterministic.py` — deterministic router → **present** (always was).
3. `token_saver` → **present** (merged `37c84302e`, as plugin `plugins/token_saver/`, byte-identical to turbo).
4. `context/working_set.py` + `retrieval.py` → **NEVER BUILT anywhere** (only spec in `MODIFICATIONS.md` §2.2, issue #92). No code in turbo, no code in simplicio.
5. `telemetry/stage_timing.py` + `cache_usage.py` + `token_savings.py` → **present** (merged `37c84302e`, byte-identical; plus simplicio-only `mcp_session.py`).
6. `governor/budget.py` + `policies.py` → **present as `iteration_budget.py` + `budget_config.py`** (extracted in refactor `5f309ae68`; turbo later removed the `agent/governor/` dir in cleanup — see below).
7. `registry/lazy_schema.py` + `skill_meta.py` → **ported 2026-07-12** from turbo git history (turbo removed it in cleanup `c8af8799f`; last good rev `5dad551d5`) → **PR #216**.
8. `distributed/protocol.py` → **materialized 2026-07-12** from ADR-0006 (turbo never shipped code; only the ADR/overview docs existed) → **PR #215**.

## Truth table (verified 2026-07-12 via git)

| Module | In turbo tree? | In simplicio `main`? | Action taken 2026-07-12 |
|---|---|---|---|
| daemon / deterministic router | YES | YES | none (pre-existing) |
| token_saver | YES (plugin) | YES (`37c84302e`) | none |
| working_set / retrieval | NO (spec only) | NO | none — needs spec-based build, out of "port real code" scope |
| telemetry | YES | YES (`37c84302e`) | none |
| governor/budget | dir removed in turbo cleanup; survives as `iteration_budget`+`budget_config` | YES (`5f309ae68`) | none |
| lazy_schema / skill_meta | removed in turbo cleanup `c8af8799f` | **ported** (history `5dad551d5`) | **PR #216** |
| distributed / protocol | NEVER code (ADR only) | **materialized** from ADR-0006 | **PR #215** |

## Conclusion

The AGENTS.md claim "Simplicio = Turbo + Runtime" is **not** disproven by a
code gap — most Turbo speed axes are already in the tree. Two axes needed real
work (lazy_schema, distributed) and got PRs. One (working_set) was never built
in either repo. The remaining reason TTFT of a paid model matches Hermes
(~585 ms, measured 2026-07-11) is that those modules affect per-turn token
cost, not first-token latency — streaming + warm daemon already cover TTFT.

## Decision

1. Retract the "2/8 axes" claim. Actual inheritance is 6/8 axes already in
   tree (daemon, router, token_saver, telemetry, governor-as-iteration_budget,
   + 2 new PRs), 1 spec-only (working_set), 0 true gaps.
2. lazy_schema (#216) and distributed (#215) are the only net-new ports.
3. working_set remains a from-spec build if ever wanted — flag separately, do
   not silently invent code.

## Consequences

- Positive: honest doc state; no fabricated "missing modules" work.
- Risk: lazy_schema drift — turbo removed it; future re-sync must pull from
  turbo commit `5dad551d5`, not `main`.
- distributed is spec-materialized; the wire protocol is real but no node host
  implements it yet (skeleton only, by design).

## Follow-ups

- Merge PR #216 (lazy_schema) and PR #215 (distributed).
- AGENTS.md accuracy fix (separate PR) — restate inheritance honestly.
- working_set: decide spec-build vs drop.
