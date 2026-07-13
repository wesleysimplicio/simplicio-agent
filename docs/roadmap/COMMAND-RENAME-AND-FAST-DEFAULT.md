# `simplicio-agent` as the canonical command + fast-by-default

> Status: wave 1 landed 2026-07-08. User decision (2026-07-08): full
> user-facing surface rename with `hermes` kept as a deprecated alias;
> internal modules and the `HERMES_*` env contract stay (the runtime reads
> 100+ of those vars); performance defaults inverted (fast ON, lean is the
> explicit opt-out); PyPI rename with a `hermes-agent` transition
> meta-package. Supersedes the earlier "hermes stays the primary command"
> wording in `AGENTS.md` (updated in the same wave).

## Wave 1 — landed

- `pyproject.toml`: `simplicio-agent` is the canonical console script;
  `simplicio-agent-acp` added; `hermes`/`hermes-agent`/`hermes-acp` kept as
  deprecated aliases.
- argv[0]-aware deprecation nudge (`_warn_deprecated_alias_once` in
  `hermes_cli/main.py`, once per day via stamp file in the state dir) +
  `cli_name()` / `invoked_via_deprecated_alias()` in `hermes_constants.py`.
- ~3,200 user-facing `hermes <cmd>` strings mechanically replaced with
  `simplicio-agent <cmd>` across .py/.md/.sh/.ps1/.yml (history excluded:
  CHANGELOG, ADRs, docs/simplicio-import, TOON-CONTRACT). The
  dashboard/serve process-reaper in `hermes_cli/main.py` now matches BOTH
  command names.
- Fast-by-default: `[all]` extra now includes `[fast]` (orjson/msgspec/
  uvloop) → Docker (`uv sync --extra all`) and `install.ps1` tier-1 get the
  fast stack automatically; `scripts/install.sh` source-fallback installs
  `hermes-agent[fast]` unless `SIMPLICIO_AGENT_LEAN=1`. `uv.lock`
  regenerated. `docs/performance.md` defaults table updated.
- Hot-path `_fastjson` swaps: all 27 `json.dumps` in `mcp_serve.py` tool
  results; tool-arg parse/normalize sites in `agent/conversation_loop.py`
  (~906, ~4220); per-result parse in `batch_runner.py`. (orjson's
  JSONDecodeError subclasses `json.JSONDecodeError`, so existing except
  clauses are unaffected.)

## Wave 1.1 — faster than upstream on every shared probe (landed 2026-07-08)

`scripts/benchmark_vs_upstream.py` runs paired probes against an original
`hermes-agent` checkout (each side in its own subprocess/sys.path, using its
own default dependency posture) and FAILS if any shared probe is slower.
Measured in a Linux container, Python 3.11, orjson installed here (the
default posture after this program), upstream on stdlib:

| Probe | simplicio | hermes | speedup |
|---|---|---|---|
| json.dumps tool-result (default hot path) | 2.8 µs | 33.1 µs | **12.0×** |
| json.loads tool-args (default hot path) | 0.6 µs | 1.8 µs | **3.1×** |
| tool-arg canonicalize (loads+dumps sort_keys) | 1.2 µs | 5.2 µs | **4.5×** |
| token estimate, 200-msg history | 634 µs | 677 µs | **1.07×** |
| CLI cold import (`import hermes_cli.main`) | 66.4 ms | 117.6 ms | **1.77×** |

The cold-import win came from cutting `hermes_cli.config` (~100 ms module
body) out of the boot path entirely — it was pulled in by three thin edges:
`main.py`'s `get_hermes_home` re-export import, `hermes_logging`'s
`is_managed` (moved to `hermes_constants`, config re-exports), and
`model_setup_flows`' module-level `clear_model_endpoint_credentials` (now a
lazy proxy) — plus a fourth deferral: `env_loader` no longer imports `utils`
(→ PyYAML, ~12 ms) at module level. Fork-only modules (rust_ext,
serde/msgspec, uvloop, async_dag, http_pool, TOON, warm daemon,
kernel_binding) are listed by the script as existence wins.

Module/command parity vs upstream, audited 2026-07-08: every upstream
gateway platform exists here (built-in or under `plugins/platforms/` via
`gateway/platform_registry.py` — telegram, slack, discord, sms, email,
matrix, dingtalk, feishu, wecom, whatsapp, …) plus 11 platforms upstream
lacks (google_chat, irc, line, mattermost, ntfy, photon, raft, simplex,
teams, homeassistant, discord). Upstream-only modules NOT carried:
`agent/gemini_cloudcode_adapter.py`, `agent/google_code_assist.py`,
`agent/google_oauth.py` (Google OAuth login route) — deliberate fork
decision; revisit only if Google OAuth login is wanted as a provider plugin.

## Remaining waves

### A2 — state & env migration
- Flip the default state dir `~/.hermes` → `~/.simplicio/agent`
  (`hermes_constants.py:52`) with a one-shot startup migrator (report +
  `--no-migrate` opt-out; read-fallback for 2 releases). Fix the hardcoded
  `Path.home()/".hermes"` bypasses first: `mcp_serve.py`,
  `agent/telemetry/{token_savings,mcp_session,stage_timer}.py`,
  `skills/productivity/google-workspace/scripts/_hermes_home.py`.
- Central `env_get(name)` reading `SIMPLICIO_AGENT_X` → `HERMES_X`
  (extends the existing HOME dual-read). Start with the ~30 user-documented
  vars, not all 525. Prereq: a generated env-var registry
  (`docs/ENV_VARS.md` + `agent/env_registry.py`).
- Docker identity: `image: simplicio-agent`, `/opt/simplicio-agent`,
  `simplicio` user, shim on PATH as `simplicio-agent` + `hermes` symlink.
  Homebrew: new `simplicio-agent.rb`, old formula `deprecate!`.
- Locales: 192 "Hermes" strings across 15 language YAMLs.

### A3 — package identity (coordinate with release flow)
- PyPI `name = "simplicio-agent"`; publish `hermes-agent` as a transition
  meta-package (depends on `simplicio-agent==X`) for 2–3 releases; extras
  rename together. Rust crate `hermes-fast` → `simplicio-fast` with a
  `hermes_fast` import shim.

### B2 — remaining hot-path wiring (each needs an A/B benchmark)
- **Token budget estimator** (highest traffic):
  `estimate_messages_tokens_rough` (`agent/model_metadata.py:2170`) —
  delegate to `agent/tokens/fast_estimator` (tiktoken) and/or the Rust
  `estimate_messages_tokens_bytes`. NOT a blind swap: current semantics
  count images at a flat 1500 tokens; any replacement must preserve that
  or budget decisions shift. Bench first (`scripts/benchmark_e2e.py`).
- ~~**kernel_binding warm mode**~~ **Landed 2026-07-09** (#109 +
  simplicio-runtime#2983, opt-in via `SIMPLICIO_AGENT_KERNEL_WARM=1`):
  `tools/kernel_binding.py`'s `_WarmKernelClient` reuses one
  `simplicio serve --mcp --stdio` connection (raw NDJSON-over-stdio, no
  `mcp` package dependency) instead of a fresh `subprocess.run` per call.
  Only `gate classify --action <x> --json` is routed today — the one MCP
  tool (`simplicio_gate`) the runtime now serves **in-process**
  (`mcp_call_tool` self-execs a fresh process for every other tool;
  `simplicio_gate` got the same inline treatment `simplicio_run` already
  had). Measured against a local runtime build: **cold (subprocess.run)
  ~65 ms/call median vs. warm steady-state ~0.4 ms/call — ~160-174×**
  (`scripts/benchmark_kernel_warm.py`, 2 runs of 15/30 iterations). Any
  failure at any layer (spawn/handshake/timeout/malformed
  response/tool-level error) falls through to the classic subprocess path
  unchanged — warm mode only ever changes latency, never fail-closed
  semantics. `orient_map`/`memory_recall`/`edit_mechanical` are NOT routed
  yet: they'd still pay a full process spawn server-side (just moved
  inside the Rust self-exec, with an extra JSON-RPC hop on top) until the
  runtime lands their in-process fast paths too — tracked in
  simplicio-runtime#2983's remaining scope.
- **Warm daemon auto-start** for interactive profiles
  (`hermes_cli/daemon.py`): needs an idle TTL so background daemons don't
  leak; opt-out `SIMPLICIO_AGENT_NO_DAEMON=1`.
- `async_dag.run_dag_tool_batch` call site for dependent tool chains.
- Cold start: lazy-import the ~45 `build_*_parser` modules in
  `hermes_cli/main.py` (measured ≈0.56 s import in a stock container,
  `hermes_cli.config` alone ≈0.24 s). Roadmap issue #58.
- TOON default-on for new sessions (`HERMES_SIMPLICIO_PROMPT`), session-
  pinned (cache-sacred).
- ~~Prebuilt Rust wheels (maturin) in the release CI so `rust_ext` stops
  being a dev-only build.~~ **Landed (partial) 2026-07-13** (#113):
  `.github/workflows/release.yml`'s `build-rust-ext-wheel` job builds a
  `hermes_fast` manylinux **x86_64-only** wheel with `maturin-action` and
  attaches it to the GitHub Release; `tests/agent/test_hermes_fast.py`
  gained real-extension assertions (`requires_rust_extension`, skipped
  when the wheel isn't installed) that this job now exercises for real
  instead of only ever hitting the pure-Python fallback in CI.
  aarch64/macOS/Windows wheels are intentionally out of scope for this PR —
  scoped down to keep the change reviewable; see issue #113 for the
  follow-up matrix.

### B3 — proof
- CI perf-regression gate: `scripts/benchmark_e2e.py --json` +
  `scripts/turbo-speed/01..04` vs committed baselines; fail PRs on
  regression. Covers epic #25 DoD ("beat Hermes Turbo in TTFT and
  tool-loop with documented margin").
- Per-turn TTFT/tool-loop telemetry into the savings ledger so "faster" is
  `measured`, not `estimated`.

## Explicitly out of scope (decided)
- Renaming the ~6,385 internal `hermes_*` imports/module paths, or the
  `HERMES_*` env prefix. Zero user value, breaks the agent↔runtime
  contract on both sides.
