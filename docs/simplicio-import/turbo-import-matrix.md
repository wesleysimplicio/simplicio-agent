# hermes-turbo-agent -> simplicio-agent — performance import matrix

> Deliverable for #19 (F1, sub-issue of epic #18). Scope: **performance deltas
> only** — the pillar #18 assigns to `hermes-turbo-agent`. General Hermes
> feature/bugfix drift (new providers, MoA, branding) is explicitly out of
> scope for this document; see "Out of scope" at the bottom.

## Compared refs

- `simplicio-agent` (this repo): `5d9c2852cad0f14b6511c3e5840b80fca3727a64` (2026-07-02)
- `wesleysimplicio/hermes-turbo-agent`: `485a58c9fb6c86b768b70ef75fef72a7597874e3` (2026-07-01)

## Method

1. Byte-diff the files/dirs the issue names explicitly as the perf surface:
   `agent/_hermes_fast.py`, `agent/_fastjson.py`, `rust_ext/`,
   `agent/async_dag/`, `agent/context_compressor.py`,
   `agent/conversation_compression.py`, `agent/conversation_loop.py`.
2. Grep/diff the issue's "candidatos prováveis" list: streaming completion,
   prewarm KV/connection, batching tool-calls, parallelização do tool-loop,
   overhead do conversation_loop, lazy imports/startup time.
3. `diff -rq agent/ <turbo>/agent/` for a full file-level manifest, then
   triage every file that differs or is turbo-only into (a)-(d), reading the
   actual diff for anything perf-shaped.

## Category (a) — already exists here, equivalent or better (no action)

| Item | Evidence |
|---|---|
| `agent/_hermes_fast.py` (PyO3 bridge, measured dispatch policy) | byte-identical (`diff` empty) |
| `agent/_fastjson.py` (orjson wrapper + stdlib fallback) | byte-identical |
| `rust_ext/` (Cargo.toml, pyproject.toml, `src/`) | byte-identical, all files |
| `agent/async_dag/` (DAG executor for dependent tool batches) | byte-identical, all files |
| `agent/conversation_compression.py` | byte-identical |
| `agent/jiter_preload.py` (startup/lazy-import prewarm of `jiter`) | byte-identical |
| `hermes_bootstrap.py` (process bootstrap, prewarm hooks) | byte-identical |
| `agent/net/http_pool.py` core logic (opt-in HTTP/2 connection pool) | byte-identical except a docstring (see category d) |

Conclusion: the five files/dirs the issue calls out as "already ported" are in
fact **byte-identical** to hermes-turbo-agent HEAD — this repo is not behind
on any of them. Same for the "prewarm" and "lazy import/startup" candidates
from the probable-candidates list (`jiter_preload.py`, `hermes_bootstrap.py`):
zero drift.

## Category (b) — exists here, turbo is measurably ahead (import candidates)

### B1. `context_compressor.py` — 3 hot-path JSON call sites still on stdlib `json`

Turbo added `from agent._fastjson import loads as _fast_loads, dumps as _fast_dumps`
and swapped 3 of the 4 `json.loads`/`json.dumps` calls in the file (tool-arg
shrinking on the compression hot path: `_shrink_tool_call_args_for_summary`,
`_summarize_tool_result_for_context` argument parsing). The 4th call site
(`json.loads` inside `compress()` proper, ~line 1412) is **deliberately left
on stdlib** in turbo too — i.e. this is the same measured, partial-adoption
policy `_hermes_fast.py` already documents here (`orjson`/Rust only where it
wins), not a blind find-replace.

- Where it fits: `agent/context_compressor.py` lines ~363, ~380, ~505 (this
  repo's current line numbers).
- Risk: low. `_fastjson.py` is already vendored byte-identical here and used
  elsewhere in the codebase; this is a call-site swap, not new machinery. No
  prompt-cache impact (compression output format is unchanged, only the
  parser/serializer implementation).
- Import issue: opened as **#68** with an A/B benchmark defined (wall-clock
  of `_shrink_tool_call_args_for_summary` over a corpus of large tool-result
  payloads, stdlib `json` vs `agent._fastjson`, N=1000 iterations).

### B2. `tool_executor.py` — no timeout guard on concurrent tool-call batches

Turbo added `HERMES_CONCURRENT_TOOL_TIMEOUT_S` (default 420s, deliberately
above the stock `auxiliary.web_extract` 360s timeout) to
`execute_tool_calls_concurrent()`'s wait loop: past the deadline it cancels
unfinished futures, sets the interrupt flag on the stuck worker threads, and
returns rather than blocking the whole batch (and therefore the whole
tool-loop turn) indefinitely on one hung tool call. This repo's
`execute_tool_calls_concurrent()` has the same thread-pool parallelism but no
deadline — a single hung tool call in a parallel batch blocks the entire
batch (and the turn) forever.

- Where it fits: `agent/tool_executor.py`, the `concurrent.futures.wait(...)`
  loop inside `execute_tool_calls_concurrent`.
- Risk: medium — touches the tool-loop's core parallel-execution path
  directly (mentioned as a risk category in #19: "contrato de tools?" — yes,
  bounds it). Needs care that cancellation semantics match what callers
  already expect from a normal `partial`/timeout tool result.
- Import issue: opened as **#69** with an A/B benchmark defined (inject one
  artificially-hung tool call into an otherwise-fast concurrent batch;
  measure batch wall-clock and whether the turn completes vs hangs, with vs
  without the guard).

## Category (c) — doesn't exist here, candidate to import

### C1. `agent/tier_rate_limiter.py` + dedup in `tools/async_delegation.py`

Turbo-only file `agent/tier_rate_limiter.py`: a thread-safe, per-tier
token-bucket (`TierRateLimiter`), used by `tools/async_delegation.py` to cap
*how often* subagent dispatch opens per role/minute — independent of and
complementary to the existing concurrency cap (`max_async_children`), which
bounds *how many* run at once but not the rate a model can retrigger
dispatch. Turbo also adds `_dedupe_key()` in the same file: a
deterministic sha256 fingerprint of `(goal, context, toolsets, role, model)`
used to detect an in-flight duplicate dispatch (e.g. a retried tool call for
the exact same task) and return the existing delegation instead of spawning
a second one for identical work — a direct efficiency win (avoids redundant
subagent execution), not just a bugfix.

- Where it fits: new `agent/tier_rate_limiter.py` + a wiring change in
  `tools/async_delegation.py` (new `dispatch_rate_per_minute` optional
  parameter, `None` default = today's behavior unchanged).
- Risk: medium — new module (low risk in isolation) + a call-site change in
  the delegation gate. Ties directly into the mandatory guardrail rule this
  repo's AGENTS.md/CLAUDE.md already carries (yool §11: cpu/disk/timeout
  quotas on every loop/fan-out) — this is a rate guardrail for exactly that
  surface, so it is aligned with, not competing against, existing policy.
- Import issue: opened as **#70** with an A/B benchmark defined (1: dedup hit
  rate — replay a burst of N dispatches with a known fraction of exact
  duplicates, measure redundant subagent invocations avoided; 2: rate-limit
  effectiveness — synthetic burst dispatch loop, measure dispatches/minute
  with vs without the limiter engaged).

### C2 (minor, non-perf but forward-compat — noted, not opened as its own issue)

`tools/async_delegation.py` also carries a Python 3.14 `ThreadPoolExecutor`
internals compatibility shim (stdlib restructured `_worker`'s signature in
3.14). Not a speed win — a forward-compat correctness fix. Folding it into
the C1 import (#70) rather than a separate issue since it lives in the same
file and same touched function; call out explicitly in that PR's diff.

## Category (d) — exists here, not in turbo (export/ignore, no import)

| Item | Note |
|---|---|
| `agent/toon_codec.py`, `agent/toon_boundary.py` (TOON codec) | This repo has it, turbo doesn't. Already tracked by #14/#15/#16 per epic #18's body — no new action here. |
| `agent/net/http_pool.py` docstring | This repo carries an extra clarifying paragraph turbo lacks (documents `HttpPool` as an intentional opt-in utility, not dead code, citing `CHANGELOG.md` [0.21.0]). Cosmetic; nothing to import, arguably worth upstreaming to turbo but that's outside this repo's control. |

## Out of scope (explicitly NOT part of this matrix)

A full `diff -rq agent/ <turbo>/agent/` shows **43 files differ** and 6 files
exist only in turbo (`auto_mapper.py`, `hermes_turbo_home_bootstrap.py`,
`metrics.py`, `moa_trace.py`, `tier_rate_limiter.py` [covered above],
`vertex_adapter.py`). The overwhelming majority of that drift is **not
performance work** — it's general Hermes-fork feature/bugfix drift
unrelated to the "velocidade" pillar #18 assigns to hermes-turbo-agent:

- New provider adapters: `vertex_adapter.py`, changes to `anthropic_adapter.py`,
  `credential_pool.py`, `error_classifier.py` (Vertex 401 retry, Nous
  entitlement messaging).
- Mixture-of-Agents (MoA) feature: `moa_loop.py`, `moa_trace.py`, and the bulk
  of the `conversation_loop.py`/`context_compressor.py` diffs audited above
  (MoA cost accounting, summary-role selection edge cases, orphaned
  tool-call sanitization, turn-pair-aware compaction cut points). Read in
  full during this audit; **zero of it is perf-shaped** — it's correctness
  and cost-accounting work layered on top of the loop, not a hot-path
  optimization. Confirmed by the fact the *speed-critical* file in the same
  diff (`_fastjson`-backed helpers) shows the measured, partial-adoption
  pattern while the rest is pure feature work.
- `hermes_turbo_home_bootstrap.py`: turbo-brand-specific `$TOTA_HOME` seeding
  (`.hermes_turbo/` source tree, "Hermes Turbo" identity strings) — not
  portable to `simplicio-agent`'s own identity/bootstrap without a rename;
  not a perf item either way.
- `agent/metrics.py`: turbo-only, but dead code — not imported by anything
  else in hermes-turbo-agent (`grep` for `agent.metrics` finds zero
  consumers) and depends on `prometheus_client`, a **new external
  dependency** this repo's policy requires human confirmation for. Rejected:
  no consumer, no measured benefit, undisclosed new dep.
- `run_agent.py` (5710 lines here vs 16619 in turbo) and `cli.py`: both
  differ enormously, but not because of perf work — this repo has already
  split a large amount of `run_agent.py`'s turbo-monolith logic into
  dedicated modules (`agent_runtime_helpers.py`, `tool_executor.py`,
  `tool_dispatch_helpers.py`, `turn_finalizer.py`, etc., all of which *do*
  appear in the file-level diff above and were individually checked). A full
  line-by-line reconciliation of the remaining `run_agent.py`/`cli.py`
  divergence is an architecture-level question (closer to epic #18's F2
  "kernel binding" than to F1's perf inventory) and is intentionally left out
  of this matrix rather than rubber-stamped here.

If a future pass wants that broader sync, it should be scoped as its own
issue against F2 or a dedicated "general Hermes sync" epic — not folded
silently into this perf-only matrix.
