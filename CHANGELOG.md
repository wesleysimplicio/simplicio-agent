# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

`simplicio-agent` becomes the canonical command and the fast stack becomes
the default (user decision 2026-07-08; wave 1 of
`docs/roadmap/COMMAND-RENAME-AND-FAST-DEFAULT.md`).

### Changed

- **Canonical CLI command is now `simplicio-agent`** (`pyproject.toml`
  scripts): `simplicio-agent-acp` added; `hermes`, `hermes-agent` and
  `hermes-acp` keep working as deprecated aliases that print a once-per-day
  nudge (`_warn_deprecated_alias_once`, stamp-file throttled). All
  user-facing `hermes <cmd>` hints (~3,200 strings across CLI, docs,
  installers, tips, locales-adjacent files) now say `simplicio-agent <cmd>`;
  historical records (CHANGELOG, ADRs, hermes-import logs) untouched. The
  dashboard/serve stale-process reaper matches both command names.
- **Fast paths are default-on for full installs**: `[all]` now includes
  `[fast]` (orjson, msgspec, uvloop), so the Docker image and the Windows
  installer tier-1 get them automatically; `scripts/install.sh` installs
  `hermes-agent[fast]` unless `SIMPLICIO_AGENT_LEAN=1`. Bare
  `pip install hermes-agent` stays lean with pure-Python fallbacks.
  `uv.lock` regenerated (also syncs the locked project version, previously
  stale at 0.21.1).
- **Hot-path JSON on orjson**: MCP tool-result serialization
  (`mcp_serve.py`, 27 sites), tool-call argument parse/normalize in
  `agent/conversation_loop.py`, and per-result parsing in
  `batch_runner.py` now route through `agent/_fastjson` (graceful stdlib
  fallback; orjson's `JSONDecodeError` subclasses the stdlib one, so error
  handling is unchanged).
- `AGENTS.md` product-identity policy updated: canonical command is
  `simplicio-agent`; internal module paths and the `HERMES_*` env contract
  still never change (the runtime reads 100+ of those vars).

### Added

- **`scripts/benchmark_vs_upstream.py`** — paired benchmark against an
  original `hermes-agent` checkout that exits non-zero if any shared probe
  is slower here. Measured 2026-07-08 (Linux, py3.11): JSON dumps 12.0×,
  loads 3.1×, tool-arg canonicalize 4.5×, token estimate 1.07×, CLI cold
  import 66.4 ms vs 117.6 ms (1.77×). The cold-import win cut
  `hermes_cli.config` (~100 ms module body) out of the boot path via three
  thin-edge fixes (`get_hermes_home` import, `is_managed` moved to
  `hermes_constants`, lazy `clear_model_endpoint_credentials` proxy).
  Results published in the READMEs (all 4 languages),
  `docs/performance.md`, and `docs/roadmap/COMMAND-RENAME-AND-FAST-DEFAULT.md`.

## [0.23.0] - 2026-07-04

Product launch hardening for the Simplicio Agent MCP server — gate the paid
surface behind a subscription and stop the product leaking internals.

### Added

- **Subscription gate on `simplicio-agent mcp serve`** (`mcp_serve.py`): the MCP
  server is now a subscription-only product surface. `run_mcp_server()` checks
  entitlement before starting and refuses to serve when the account is not
  entitled, printing a billing/login nudge to stderr and exiting non-zero. The
  check reuses the existing Nous Portal entitlement chain
  (`hermes_cli.nous_account.get_nous_portal_account_info` +
  `format_nous_portal_entitlement_message`) so "subscribed" has a single source
  of truth. Fails closed: an account-lookup error or a missing entitlement
  module denies access rather than allowing it.
- **`SIMPLICIO_MCP_ALLOW_UNLICENSED`** env escape hatch: any truthy value
  bypasses the subscription gate for self-hosted / dev / CI runs. Unset in the
  hosted product so access stays subscription-only.
- **`SIMPLICIO_NO_SOURCE_FALLBACK`** env for `scripts/install.sh`: when set and
  no compiled binary is available for the platform, the installer exits instead
  of falling back to a pip-from-git or git-clone **source** install — so a
  product/enterprise install never pulls the full source tree onto a customer
  machine. Default (unset) preserves the existing self-host fallback behaviour.

### Security

- **No internal detail in MCP tool errors** (`mcp_serve.py`): `messages_read`,
  `attachments_fetch`, and `messages_send` no longer interpolate raw exception
  text / `ImportError` module paths into the JSON returned to MCP clients. They
  now return generic messages and log the detail at DEBUG only, so tracebacks,
  internal module names, and filesystem paths are not exposed to end users.

### Changed

- Rebranded the MCP server logger from `hermes.mcp_serve` to
  `simplicio.mcp_serve` and the `run_mcp_server` banner to "Simplicio Agent".

## [0.22.0] - 2026-07-02

### Added

Follow-up work from the "how much better are we than upstream Hermes"
question (issues #9-#12): make the perf-layer claims measurable, documented,
and the sync tooling's remaining placeholder real.

- **`scripts/benchmark_e2e.py`** (issue #9): standalone, offline benchmark
  harness. Measures `agent.serde` (fast JSON) vs stdlib `json`,
  `agent.tokens` (tiktoken) vs the naive `len // 4` estimator,
  `agent.prompt_caching.apply_anthropic_cache_control`'s current
  shallow-copy-of-≤4-messages strategy vs a reimplemented pre-0.19.0
  full-transcript-deepcopy baseline, `agent.think_scrubber` streaming
  throughput, `agent.router`'s deterministic no-LLM fast path latency, and
  CLI cold-import time as a startup proxy. Every scenario runs against
  whatever is actually installed, with an explicit fallback-path call for
  the two toggleable backends — so `--json` output is a real "with extras
  vs baseline" number, not a microbenchmark claim.
- **`docs/performance.md`** (issue #10): single reference for every perf
  module — what triggers it, what the fallback is, how to enable it, and
  what's on by default (nothing beyond core `httpx`; `pip install
  "hermes-agent[fast]"` is the one extra worth reaching for). Records the
  decision that the base installer intentionally does not request `[fast]`.
- **`hermes doctor`** (issue #10): new "Performance Modules" section
  (`hermes_cli/doctor.py`) reporting live status of fast JSON, fast token
  estimator, uvloop, the Rust hot-path extension, `HttpPool`/httpx, the
  `HERMES_SIMPLICIO_PROMPT` gate, and the warm daemon — mirrors the
  existing "Required Packages" check pattern.
- **`agent/net/http_pool.py`** (issue #12): documented the decision to keep
  `HttpPool` as a tested, opt-in utility for plugin/MCP-transport authors
  rather than dead code — it has no call site in this repo's own SDK-managed
  HTTP calls (see [0.21.0]) but remains a legitimate public surface.
- **`scripts/sync/ecosystem-sync.sh` `asolaria-absorb --apply`** (issue
  #11): the subcommand was a read-only placeholder whose pending-item grep
  never matched anything (the plan had no checkboxes). Added a "Status
  tracking" checklist to `docs/ASOLARIA_ABSORPTION_PLAN.md` and a canonical
  `ASOLARIA_ITEMS` table (id/priority/license-class/title) to the script.
  `--apply --complete <id>` now checks off one item after a human confirms
  the (re)implementation landed — `reimplement-only` items (7 of 9; NO
  LICENSE / NOASSERTION sources) additionally require
  `--confirm-reimplemented` and are never auto-copied; the tool never
  vendors source itself, only tracks status and runs the `validate` gate
  afterward. `docs/SYNC_PIPELINE.md` updated to match.

## [0.21.1] - 2026-07-01

### Fixed

- **`hermes_cli/main.py`**: added the `daemon` subcommand (registered in
  0.21.0's warm-daemon port) to `_BUILTIN_SUBCOMMANDS`. Without it, `hermes
  daemon` was paying the eager plugin-discovery cost on every invocation
  instead of taking the fast path every other built-in subcommand gets.
  Caught by `test_startup_plugin_gating.py::test_builtin_set_covers_every_registered_subcommand`.

## [0.21.0] - 2026-07-01

### Added

Connected every remaining orphaned performance module (ported earlier from
the hermes-turbo-agent fork) to a real production code path. Each was
previously a library exercised only by its own unit tests.

- **`agent.tracing`**: wraps the real per-attempt streaming API call in
  `interruptible_streaming_api_call` (`agent/chat_completion_helpers.py`)
  with `span("llm.stream_call", ...)`, recording provider/model/attempt and
  chunk/byte counts. Side-effect only; re-raises unchanged on error.
- **`agent.router`** (deterministic, no-LLM): wired into
  `GatewayRunner._handle_message` (`gateway/run.py`) as a last-resort fast
  path — only runs when no slash/quick/plugin/skill command already
  matched, so trivial inputs (help/date/time/ping/echo) answer instantly
  without an LLM round-trip, with zero collision with existing dispatch.
- **`agent.async_dag`**: `run_dag_tool_batch` added alongside the existing
  thread-pool parallel batch in `agent/tool_executor.py` — an opt-in
  primitive for genuinely dependent tool-call chains.
- **`agent.providers`** (`ProviderChain`): `is_transient_fallback_error` +
  `build_fallback_provider_chain` added to `hermes_cli/fallback_config.py`
  as additive helpers layered on the existing config-merge fallback.
- **`agent.project_mapper`**: `detect_fingerprint` wired into
  `build_system_prompt_parts` (`agent/system_prompt.py`) — surfaces the
  detected stack as one context-tier line, best-effort.
- **`agent.simplicio_prompt`**: mirrored the sister fork's exact
  `agent/transports/__init__.py` wiring. Env-gated
  (`HERMES_SIMPLICIO_PROMPT`), off by default.
- **`agent.serde`**: wired into `agent/telemetry/receipts.py`'s
  read/write paths in place of stdlib `json`.
- **`hermes_cli/daemon.py`** (warm daemon): ported from the sister fork
  and made real — every preloader stub replaced with a genuine query
  against this repo's actual tool registry, skills index, provider
  metadata, MCP catalog, and recent session summaries. Registered as a
  `hermes daemon` subcommand.

### Notes

- **`agent.net` (`HttpPool`)**: investigated every raw-HTTP call site in
  the repo; none is a safe, repeated-same-base-url candidate that isn't
  already SDK-managed — left unwired rather than forced.
- **`agent/metrics.py`**: not ported. No real hit/miss/TTL cache exists in
  this repo to attach its four Prometheus gauges to.

## [0.20.0] - 2026-07-01

### Added

- **Ecosystem sync pipeline tooling** (`scripts/sync/ecosystem-sync.sh`,
  `.github/workflows/ecosystem-sync.yml`, `docs/SYNC_PIPELINE.md`): repeatable
  orchestrator for the Hermes -> Hermes Turbo -> Simplicio sync flow.
  - Subcommands: `turbo-absorb-hermes` (Turbo fetches NousResearch/hermes-agent
    and stops for human review; `--apply` stages a non-destructive merge),
    `simplicio-pull-perf` (copies the additive perf module set from Turbo,
    skipping any file newer in Simplicio, then runs the validation gate),
    `ecosystem-update` (parameterizable pull of other `Projetos/ai` repos),
    `asolaria-absorb` (read-only placeholder listing pending items from
    `docs/ASOLARIA_ABSORPTION_PLAN.md`), and `validate` (perf import smoke +
    targeted pytest gate).
  - **Ordering guard**: enforces that Turbo absorbs the latest Hermes BEFORE
    Simplicio pulls, because Simplicio is newer than Turbo; the perf delta is
    pulled additively (never wholesale-overwriting newer Simplicio files).
  - Every destructive step is guarded behind `--apply`; `--dry-run` is the
    default. All actions are logged as copied / would-copy / skipped-newer /
    skipped-identical / needs-human-review — never a silent overwrite.
  - CI workflow is dry-run by default and never auto-pushes synced content; a
    human opts into `--apply` via a `workflow_dispatch` input.

## [0.19.0] - 2026-07-01

### Changed

Deep hot-path performance integration ported from the hermes-turbo-agent fork's
`perf: cut hot-path allocations in caching, streaming, scrubber, state` pass,
adapted to this newer baseline — semantics preserved, 124 hot-path tests pass:

- **`agent/chat_completion_helpers.py`**: replace `len(repr(chunk))` /
  `len(repr(event))` per streamed token with a cheap delta-length byte proxy
  (content + reasoning + tool-arg, or text + thinking + partial_json). Avoids
  rendering the whole pydantic chunk/event into a throwaway string on every token.
- **`agent/prompt_caching.py`**: `apply_anthropic_cache_control` shallow-copies
  the message list and deep-copies only the ≤4 cache-marked messages instead of
  deep-copying the entire transcript on every Anthropic send. Never-mutate-the-
  caller contract preserved (verified).
- **`agent/think_scrubber.py`**: precompute lowercased tag tuples
  (`_OPEN_TAGS_LOWER` / `_CLOSE_TAGS_LOWER`); drop per-delta `tag.lower()` across
  all five scan helpers.

### Notes

Intentionally not ported from the same fork pass: the `run_agent.py` repr-proxy
sites (this newer baseline's streaming code already differs / lacks them), the
`hermes_state.py` fast-json `tool_calls` read (no `_json_loads` helper here plus
unrelated pending local edits), and the streamed tool-call `arg_parts`
accumulation (this baseline has multiple argument read-sites; converting all
safely is out of scope for this focused pass — the `+=` path stays correct).

## [0.18.0] - 2026-07-01

### Added

Ported the performance modules from the `hermes-turbo-agent` fork as additive,
optional capabilities on top of the current (newer) Hermes baseline. Nothing is
forced on by default; every fast path degrades gracefully to the existing
pure-Python behavior when the optional dependency or native extension is absent.

- **Fast JSON** (`agent/_fastjson.py`, `agent/serde/`): orjson/msgspec-backed
  encode/decode with a stdlib `json` fallback. 2-10x faster on hot paths.
- **Rust hot-path bridge** (`rust_ext/`, `agent/_hermes_fast.py`): optional
  `hermes_fast` PyO3 extension for streaming tool-call JSON parsing and token
  estimation, with a drop-in pure-Python fallback when the extension isn't
  built.
- **Fast token estimator** (`agent/tokens/`): tiktoken fast path with a naive
  `len // 4` fallback.
- **uvloop event loop** (`agent/uvloop_utils.py`, `agent/async_dag/`): installs
  the uvloop policy when available. Wired into the gateway daemon
  (`gateway/run.py`) and the CLI entry point (`hermes_cli/main.py`); no-op on
  Windows or without the optional dep.
- **DAG async executor** (`agent/async_dag/`): dependency-aware parallel tool
  batch executor (Kahn topological levels + bounded concurrency).
- **Deterministic + cost-aware router** (`agent/router/`): regex no-LLM router
  for trivial intents plus a multi-tier cost-aware router with USD accounting.
- **Telemetry** (`agent/telemetry/`): stage timing, token-savings ledger, gain
  analytics, savings report, and content-addressable receipts (all stdlib,
  no secrets).
- **Provider resilience** (`agent/providers/`): fallback chain with jittered
  exponential backoff and transient-error classification.
- **HTTP/2 connection pool** (`agent/net/`): keep-alive pool over
  `httpx.AsyncClient` (optional `httpx[http2]`).
- **Lightweight tracing** (`agent/tracing/`): OTel-compatible span emitter
  without the heavy `opentelemetry-sdk`.
- **Project fingerprint** (`agent/project_mapper/`): stdlib manifest-based stack
  detection.
- **simplicio-prompt** (`agent/simplicio_prompt.py`): optional, env-gated
  (`HERMES_SIMPLICIO_PROMPT`) system-prompt preparation. Shipped as a module;
  not wired into the transport hot path.
- **token-saver plugin** (`plugins/token_saver/`): compacts noisy terminal/tool
  output while preserving redacted evidence handles (`HERMES_TOKEN_SAVER_MODE`).
- **`fast` / `perf` install extras** (`pyproject.toml`): `orjson`, `msgspec`,
  `uvloop`. `maturin` added to the `dev` extra to build `rust_ext`.
- Test suites for every ported module (126 tests passing).

### Notes

- Not ported: the fork's rebrand (Tota → Hermes Turbo), upstream-sync tooling,
  benchmark/PDF scripts, and `agent/auto_mapper.py` / `agent/metrics.py` (the
  latter two are coupled to fork-specific branding or a hard `prometheus_client`
  dependency and add no standalone runtime win here).
