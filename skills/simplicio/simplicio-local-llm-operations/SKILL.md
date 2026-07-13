---
name: simplicio-local-llm-operations
description: Keep Simplicio's local LLM always active on macOS, expose a stable local OpenAI-compatible endpoint, and wire the runtime to use it by default. Use for local-model startup, daemonization, endpoint verification, and recovery after llama.cpp/launchd drift.
---

# Simplicio Local LLM Operations

## When to use
- The user wants the local LLM **always active**.
- You need Simplicio to expose or consume a stable local OpenAI-compatible endpoint.
- You need to daemonize `llama-server` on macOS with `launchd`.
- The runtime is healthy but the local model is still cold or only starts on demand.

## Core rule
Prefer a **host-level always-on daemon** for the local model and make the runtime consume that endpoint explicitly. For macOS, the durable mechanism is a `LaunchAgent`, not an ad-hoc shell background process.

## Canonical outcome
1. A user LaunchAgent keeps `llama-server` running.
2. It serves the repo-local GGUF over `127.0.0.1:<port>`.
3. The Simplicio runtime LaunchAgent exports `SIMPLICIO_LOCAL_OPENAI_BASE_URL=http://127.0.0.1:<port>/v1`.
4. Verification proves both:
   - the daemon is `running` in `launchctl`
   - the HTTP endpoint returns `200`

## Canonical model preference
- If the user has defined a canonical local model name, treat that as the target of truth for configuration and communication, even if the currently running daemon reports a different model ID.
- Separate **current state** from **desired canonical state** when reporting: state from status probes, preference from user-defined configuration.
- When these differ, say so explicitly and avoid presenting the current daemon identity as the canonical choice.

## macOS procedure

### 1) Verify the local model path
Use the runtime's own model surface first:
- `simplicio model status --json`

Only proceed when:
- `status = valid`
- `offline_ready = true`
- the `path` points to a real GGUF

### 2) Create a LaunchAgent for the local model
Write a plist under:
- `~/Library/LaunchAgents/com.simplicio.local-llm.plist`

Recommended shape:
- `ProgramArguments[0] = /opt/homebrew/bin/llama-server`
- `-m <gguf-path>`
- `--host 127.0.0.1`
- `--port 11435`
- `-c 8192`
- `-b 128`
- `-ub 32`
- `--parallel 1`
- `-t 4`
- `--n-gpu-layers 99`
- `--mmap`
- `RunAtLoad = true`
- `KeepAlive = true`
- stdout/stderr log files under `~/.simplicio/logs/`

### 3) Wire the runtime to the daemonized endpoint
Update the runtime LaunchAgent plist:
- `~/Library/LaunchAgents/com.simplicio.runtime.plist`

Add environment variable:
- `SIMPLICIO_LOCAL_OPENAI_BASE_URL=http://127.0.0.1:11435/v1`

This makes the runtime advertise and consume the local OpenAI-compatible endpoint by default.

### 4) Reload both agents
Use `launchctl`:
- bootout (ignore failure if not loaded)
- bootstrap
- kickstart

Do this for both:
- `com.simplicio.local-llm`
- `com.simplicio.runtime`

### 5) Verify with live evidence
Must verify all of the following:
- `launchctl print gui/$(id -u)/com.simplicio.local-llm` shows `state = running`
- `http://127.0.0.1:11435/health` returns `200`
- `http://127.0.0.1:11435/v1/models` returns `200`
- `launchctl print gui/$(id -u)/com.simplicio.runtime` shows `SIMPLICIO_LOCAL_OPENAI_BASE_URL`
- `simplicio model status --json` still reports `valid` and `offline_ready = true`

## Pitfalls
- **8 GB Mac — one local LLM:** avoid running Qwen (`com.simplicio.local-llm`) **and** Gemma (`com.wesleysimplicio.llama-gemma4`) together; Gemma with `-c 65536` reserves huge KV and triggers swap. Use one daemon or ctx ≤8192. Cross-ref `simplicio-agent-fast-stack` → `references/macos-resource-pressure.md`.
- Do **not** stop at `offline_ready=true`; that means the model is usable, not necessarily daemonized.
- Do **not** claim “always active” until `launchctl` and HTTP checks both pass.
- If `llama-server` rejects a CLI flag, fix the plist and reload the agent instead of treating the feature as broken.
- Prefer loopback (`127.0.0.1`) over a public bind for the always-on local endpoint.
- Keep the runtime and model daemon as separate agents: one serves the model, the other serves Simplicio.

## Recovery pattern
If the local daemon fails to come up:
1. inspect the LaunchAgent stderr log
2. remove invalid CLI flags from `ProgramArguments`
3. reload with `launchctl`
4. recheck `/health` and `/v1/models`

Capture the durable fix, not the transient error.

## Evidence standard
Report only claims grounded by:
- `launchctl print ...`
- HTTP `200` from `/health` and `/v1/models`
- `simplicio model status --json`

Use the support note for a known-good macOS pattern:
- `references/macos-launchagent-always-on-local-llm.md`
- `references/canonical-model-preference.md`
