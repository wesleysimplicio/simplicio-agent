# macOS LaunchAgent pattern for always-on local LLM

## Goal
Keep Simplicio's local GGUF model loaded behind a durable local endpoint and make the runtime consume it automatically.

## Known-good shape

### Local model daemon
- Label: `com.simplicio.local-llm`
- Binary: `/opt/homebrew/bin/llama-server`
- Bind: `127.0.0.1:11435`
- Model path: repo-local GGUF under `.simplicio/models/`
- Key args:
  - `-m <gguf>`
  - `--host 127.0.0.1`
  - `--port 11435`
  - `-c 8192`
  - `-b 128`
  - `-ub 32`
  - `--parallel 1`
  - `-t 4`
  - `--n-gpu-layers 99`
  - `--mmap`

### Runtime daemon
- Label: `com.simplicio.runtime`
- Add env:
  - `SIMPLICIO_LOCAL_OPENAI_BASE_URL=http://127.0.0.1:11435/v1`

## Verification checklist
- `launchctl print gui/$(id -u)/com.simplicio.local-llm` -> `state = running`
- `GET /health` -> `200`
- `GET /v1/models` -> `200`
- `launchctl print gui/$(id -u)/com.simplicio.runtime` shows `SIMPLICIO_LOCAL_OPENAI_BASE_URL`
- `simplicio model status --json` still reports `status=valid` and `offline_ready=true`

## Durable lesson from this session
A transient daemon failure was caused by an invalid `llama-server` flag. The durable lesson is:
- when the LaunchAgent does not stay up, inspect stderr first
- remove unsupported CLI flags from the plist
- reload with `launchctl`
- only then re-verify the HTTP endpoints

Do not save the raw transient error as a rule; save the repair loop.
