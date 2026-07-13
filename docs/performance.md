# Performance Modules

Simplicio ported a set of performance modules from the `hermes-turbo-agent`
fork (see `docs/SYNC_PIPELINE.md` for how they get here and stay in sync).
Every module in this list is **additive and degrades gracefully**: with the
optional dependency or flag absent, the code path falls back to the
pre-existing stdlib/pure-Python behavior — nothing breaks, it's just slower.

Run `simplicio-agent doctor` to see the live status of every module below (section
"Performance Modules").

## Quick answer: what's on by default?

| Install | What you get |
|---|---|
| `scripts/install.sh`, `install.ps1` (tier `[all]`), Docker image | **Fast paths ON by default** (2026-07-08): `orjson`, `msgspec`, `uvloop` (skipped on Windows) come with the install — `[all]` now includes `[fast]`. |
| `pip install hermes-agent` (bare, or `.` from source) | The lean base: `httpx` (core dep) so `agent.net.HttpPool` works, but **no HTTP/2** unless `h2` is pulled in transitively; no fast JSON, no uvloop, no fast tokenizer, no Rust extension. Pure-Python fallbacks everywhere. |
| `pip install "hermes-agent[fast]"` | + `orjson`, `msgspec`, `uvloop` explicitly, on top of a bare pip install. |
| `pip install "hermes-agent[fast]" && pip install "httpx[http2]"` | + real HTTP/2 multiplexing for `HttpPool`. |
| Build `rust_ext/` with `maturin` (`pip install -e ".[dev]"` then `maturin develop -m rust_ext/Cargo.toml`) | + native Rust hot path for streaming tool-call parsing / token estimation. |

Since 2026-07-08 the supported installers default to the fast stack; the
**opt-out** is `SIMPLICIO_AGENT_LEAN=1` for `install.sh` (constrained targets:
Termux/Android, minimal containers), or simply `pip install hermes-agent`
without extras — every fast path degrades gracefully to its pure-Python
fallback, nothing breaks. This inverts the earlier lean-by-default decision:
production latency is now the default posture, leanness is the explicit
choice. `simplicio-agent doctor` shows the live status of every module below.

## Measured: faster than the original hermes-agent on every shared probe

`scripts/benchmark_vs_upstream.py` runs paired probes against an original
`hermes-agent` checkout — each side in its own subprocess/sys.path, on its
own default dependency posture — and **exits non-zero if any shared probe is
slower here**. Measured 2026-07-08 (Linux container, Python 3.11):

| Probe | simplicio-agent | original hermes-agent | speedup |
|---|---|---|---|
| json.dumps tool-result (default hot path) | 2.8 µs | 33.1 µs | 12.0× |
| json.loads tool-args (default hot path) | 0.6 µs | 1.8 µs | 3.1× |
| tool-arg canonicalize (loads + dumps sort_keys) | 1.2 µs | 5.2 µs | 4.5× |
| token estimate, 200-message history | 634 µs | 677 µs | 1.07× |
| CLI cold import (`import hermes_cli.main`) | 66.4 ms | 117.6 ms | 1.77× |

The script also lists the fork-only modules (rust_ext, serde/msgspec, uvloop,
async_dag, http_pool, TOON codec, warm daemon, kernel_binding) so "every
point covered" is auditable rather than silently skipped. Upstream has none
of the modules in this document — the comparison above covers the code paths
both sides share.

The cold-import margin comes from keeping `hermes_cli.config` (~100 ms
module body) out of the boot path (see `hermes_constants.is_managed`, the
`get_hermes_home` import in `hermes_cli/main.py`, and the lazy
`clear_model_endpoint_credentials` proxy in `model_setup_flows.py`) — plus
upstream-inherited work: lazy platform adapters and no heavy modules at boot.

## Module reference

| Module | Trigger | Fallback | Enable |
|---|---|---|---|
| `agent/serde/`, `agent/_fastjson.py` | `orjson` or `msgspec` importable | stdlib `json` | `pip install "hermes-agent[fast]"` |
| `agent/tokens/` | `tiktoken` importable | `len(text) // 4` estimate | `pip install tiktoken` |
| `agent/uvloop_utils.py` | `uvloop` importable, not Windows | asyncio default event loop | `pip install "hermes-agent[fast]"` (no-op on Windows) |
| `rust_ext/`, `agent/_hermes_fast.py` | `hermes_fast` native extension importable | pure-Python fallback in the same module | build with `maturin` (`dev` extra includes it); optionally set `HERMES_RUST_ESTIMATES=1` to prefer Rust estimates where both paths exist |
| `agent/net/` (`HttpPool`) | `httpx` importable (HTTP/2 specifically needs `h2`) | raises `HttpPoolUnavailable` if `httpx` is missing entirely; not wired into any core call site — it's an opt-in utility for plugin/MCP-transport authors making repeated calls to the same host | `pip install "httpx[http2]"`; use `HttpPool` directly in your plugin |
| `agent/router/` (deterministic router) | always available (stdlib-only) | N/A — it's a last-resort fast path in `GatewayRunner._handle_message`, only used when no slash/quick/plugin/skill command matched | always on, no flag |
| `agent/async_dag/` | always available (stdlib-only) | opt-in primitive (`run_dag_tool_batch`); the thread-pool parallel batch executor remains the default | call `run_dag_tool_batch` explicitly for dependent tool-call chains |
| `agent/providers/` (`ProviderChain`) | always available | additive layer on top of the existing config-merge fallback | wired into `hermes_cli/fallback_config.py` |
| `agent/project_mapper/` | always available (stdlib-only) | best-effort; silently omitted from the prompt if detection fails | wired into `build_system_prompt_parts` |
| `agent/tracing/` | always available (no `opentelemetry-sdk` dependency) | spans are simply not emitted anywhere consuming them | wired around the streaming API call |
| `agent/telemetry/` | always available (stdlib-only, no secrets) | N/A | `agent.serde` used for its receipts read/write when available |
| `agent/simplicio_prompt.py` | env var only | prompt unmodified | `HERMES_SIMPLICIO_PROMPT=1` (or `SIMPLICIO_PROMPT` / `YOOL_TUPLE_FULL_RUNTIME`); **off by default** |
| `hermes_cli/daemon.py` (warm daemon) | manual | every `hermes` invocation pays cold-start plugin discovery | `simplicio-agent daemon start` |
| `plugins/token_saver/` | plugin enabled | terminal/tool output not compacted | enable via `simplicio-agent plugins` |

## `agent/net` (`HttpPool`): why it's unwired, and why it stays

`HttpPool` is fully implemented, documented, and tested
(`tests/agent/net/test_http_pool.py`), but as of `CHANGELOG.md` [0.21.0] no
call site in this repo uses it: every raw-HTTP call site here is already
SDK-managed (OpenAI SDK, Anthropic SDK, etc.), and none of them is a safe,
repeated-same-base-url candidate for a hand-rolled pool.

Decision (tracked in issue #12): keep it. It's a legitimate, tested public
utility for **plugin and MCP-transport authors** who do make repeated calls
to the same host and don't get pooling for free from an SDK. Removing it
would just mean re-writing it the next time someone needs it. See the
module docstring in `agent/net/http_pool.py` for the usage example.

## Measuring the actual gain

Module-level claims like "2-10x faster JSON" are microbenchmarks of one
operation, not the agent end-to-end. For an end-to-end comparison (startup,
streaming latency, prompt-cache overhead, router fast-path savings) see
`scripts/benchmark_e2e.py` and issue #9.

## TOON token savings (`agent/toon_codec.py`, issue #14/#16)

`scripts/benchmark_e2e.py --skip serde --skip tokens --skip think_scrubber
--skip prompt_caching --skip router --skip cli_startup` runs the `toon`
scenario in isolation. It measures three payload shapes actually used at an
LLM-prompt boundary in this repo (a uniform array of objects, a tool-result
dict, and a small error payload), token-counting both the `json.dumps`
baseline and the TOON encoding of the same value.

Numbers below were captured in-repo with `agent.tokens.fast_estimator`'s
**naive `len(text) // 4` estimator** (`tiktoken` was not installed in the
environment this was measured in — `has_tiktoken()` returned `False`, and
the estimator honestly falls back rather than faking a BPE count). Install
`tiktoken` and re-run for exact BPE-tokenizer numbers; the naive estimator
tracks character-count reduction, which is what TOON actually removes, so
the *relative* savings are representative even though the absolute counts
would shift with a real tokenizer.

| Payload | JSON tokens (naive) | TOON tokens (naive) | Saved |
|---|---:|---:|---:|
| `uniform_array_20_users` (20-row array of `{id,name,active,role}`) | 320 | 125 | 60.9% |
| `tool_result_files_modified` (`write_file`-shaped, 15-item list) | 81 | 69 | 14.8% |
| `context_engine_error` (small single-key error dict) | 12 | 11 | 8.3% |

Reproduce: `source .venv/bin/activate && python3 scripts/benchmark_e2e.py --skip serde --skip tokens --skip think_scrubber --skip prompt_caching --skip router --skip cli_startup --iterations 2000`.
The pattern holds across shapes: TOON's win is concentrated in **uniform
arrays of objects** (the table-collapse case) — a small single-key error
dict barely benefits (as documented in `agent/toon_codec.py`'s own module
docstring), which is exactly why `to_toon_or_json` exists as a safe
default everywhere rather than something callers have to reason about
per-payload.

## CI performance-regression gate

`tools/perf_gate/` (issue #116) runs `scripts/benchmark_e2e.py --json` — the
one benchmark script in this repo that is already offline and emits *only*
JSON with `--json` — three times per (scenario, variant), takes the
**median** `per_op_us` to reduce run-to-run noise, and compares it against
a committed CI baseline (`tools/perf_gate/baseline_ci.json`). A regression
beyond the baseline's `threshold_pct` (20% by default) fails the
`perf-gate` job in CI.

`scripts/turbo-speed/` scenarios are explicitly **out of scope** for this
gate: those scripts interleave a human-readable table with their JSON
output and probe an installed `hermes`/`simplicio-agent` binary on PATH,
neither of which is reliably comparable across CI runner invocations —
wiring them in is a follow-up that needs a small change to their own
`--json` handling first.

**Bootstrap mode**: the committed `baseline_ci.json` ships with an empty
`metrics` map — this sandbox is not the target GitHub Actions `ubuntu`
runner, so no fabricated baseline is committed. `tools/perf_gate/compare.py`
treats an empty map as bootstrap mode: it runs and reports, but exits 0
instead of failing. The baseline is captured explicitly and reviewably
(same discipline as `tools/rename_guard/`, never an automatic side effect
of a CI run):

```bash
python3 -m tools.perf_gate.bootstrap_baseline           # writes baseline_ci.json
python3 -m tools.perf_gate.compare --json report.json   # gate check, exit 1 on regression
```
