# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
