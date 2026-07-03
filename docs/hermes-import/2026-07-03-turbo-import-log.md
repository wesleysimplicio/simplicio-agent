# hermes-turbo-agent import log — 2026-07-03

Wave 1. Issue: #19 (F1, sub-issue of epic #18). Full matrix:
[`turbo-import-matrix.md`](./turbo-import-matrix.md).

## Access

The issue recorded `hermes-turbo-agent` as out-of-scope for session access
(clone -> 403). Re-verified at the start of this session: the clone succeeds
(`git clone .../wesleysimplicio/hermes-turbo-agent`). Access is resolved —
no session-scope change was needed on this run.

## What was analyzed

- The 7 perf files/dirs the issue names explicitly: `agent/_hermes_fast.py`,
  `agent/_fastjson.py`, `rust_ext/`, `agent/async_dag/`,
  `agent/context_compressor.py`, `agent/conversation_compression.py`,
  `agent/conversation_loop.py` — byte-diffed in full.
- The issue's "candidatos prováveis" list: streaming completion (read
  `chat_completion_helpers.py`'s streaming diff in full), prewarm KV/connection
  (`jiter_preload.py`, `hermes_bootstrap.py`, `net/http_pool.py`), batching /
  parallelização do tool-loop (`tool_executor.py`, `tool_dispatch_helpers.py`),
  overhead do `conversation_loop.py` (full diff read, hunk by hunk),
  lazy imports/startup time (same prewarm files).
- File-level manifest of the entire `agent/` tree
  (`diff -rq agent/ <turbo>/agent/`) to catch anything the issue's own list
  missed: 43 files differ, 6 turbo-only files, 2 this-repo-only files.
  Every turbo-only file was opened and read; every differing file's diff
  hunks were read (not just `diffstat`'d) before triage.

## What was imported

Nothing in this wave — this is the audit/matrix issue (#19). Per the fusion
rule ("toda novidade Hermes ganha issue ANTES de implementar" — epic #18,
rule 1), each import candidate found gets its own issue with an A/B benchmark
defined **before** any code lands, not folded into this PR:

| Candidate | Category | Issue | Benchmark defined |
|---|---|---|---|
| `context_compressor.py` — swap 3 remaining `json.loads`/`json.dumps` call sites to `agent._fastjson` | (b) | #68 | wall-clock of `_shrink_tool_call_args_for_summary` over large tool-result payloads, stdlib vs fastjson, N=1000 |
| `tool_executor.py` — `HERMES_CONCURRENT_TOOL_TIMEOUT_S` guard on concurrent tool batches | (b) | #69 | inject one hung tool call into a concurrent batch, measure turn completion vs indefinite hang, with/without guard |
| `agent/tier_rate_limiter.py` + dedup key in `tools/async_delegation.py` | (c) | #70 | dedup hit-rate on a burst with known duplicate fraction; dispatch-rate ceiling under synthetic burst, with/without limiter |

## What was rejected

- `agent/metrics.py` (turbo-only) — zero consumers in hermes-turbo-agent
  itself (`grep` for `agent.metrics` import finds none), and it pulls in
  `prometheus_client`, an undisclosed new external dependency. Repo policy
  requires human confirmation before any new dependency; there is no
  measured benefit to weigh against that cost since the module is unused
  even upstream. Not imported, not issued.
- `agent/hermes_turbo_home_bootstrap.py` — hardcodes "Hermes Turbo" identity
  strings and a `.hermes_turbo/` seed-file convention specific to that fork's
  branding. Not a perf item; would need a rename/re-scope to even make sense
  here, which is a naming/identity decision, not this issue's call to make.
- `agent/vertex_adapter.py`, `agent/auto_mapper.py`, `agent/moa_loop.py`,
  `agent/moa_trace.py`, and the bulk of the `conversation_loop.py` /
  `context_compressor.py` diffs (MoA cost accounting, Vertex 401 retry,
  orphaned-tool-call sanitization, turn-pair-aware compaction) — all read in
  full; none of it is performance work. It's real, well-commented Hermes
  feature/bugfix drift, just not the "velocidade" pillar this issue audits.
  Logged as out-of-scope in the matrix rather than silently absorbed or
  silently ignored.
- `run_agent.py` / `cli.py` full reconciliation — this repo's `run_agent.py`
  is already 5710 lines vs turbo's 16619; a chunk of turbo's monolith has
  already been split into dedicated modules here. Treating the remaining gap
  as a perf-import question would be dishonest scope-stretching — it's an
  architecture question (closer to epic #18's F2) and is called out as such,
  not resolved here.

## Evidence

- `simplicio-agent` HEAD at audit time: `5d9c2852cad0f14b6511c3e5840b80fca3727a64`
- `hermes-turbo-agent` HEAD at audit time: `485a58c9fb6c86b768b70ef75fef72a7597874e3`
- Diff commands and full hunks were inspected interactively during the audit
  (not just line counts); see `turbo-import-matrix.md` for the per-item
  citations (file, approximate line numbers, and what the diff actually
  does) that back each classification.

## system_and_3 / prompt-cache check

No code changed in this PR — matrix and log are documentation only. The three
follow-up issues (#68/#69/#70) each note in their own body that the change
must not alter compression output format or system-prompt layout, per the
"cache é sagrado" rule (epic #18 rule 2); enforcement happens at review time
on those PRs, not here.
