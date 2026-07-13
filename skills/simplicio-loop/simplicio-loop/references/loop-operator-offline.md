# Loop operator offline-config pitfalls (post-mapping gate)

After the mapper-freshness fix (PR #263) the loop reaches the operator but can still fail
with `operator_failed` / `blocked`. These are the offline-config traps seen on 2026-07-12.

**User standing rule (Wesley 2026-07-12): always use a quantized Q4 model for the local
operator.** The recommended path is a `llama-server` serving a `*Q4_K_M.gguf` on
`127.0.0.1:11435` + the loop pointing at it via `SIMPLICIO_BASE_URL`. Do NOT rely on the
dev-cli bundled `--local` (MiniCPM5 1.5B) for real implementation.

## Trap 1 — operator needs an API key

`simplicio-dev-cli task` (the loop's operate operator) errors with:

```text
set SIMPLICIO_API_KEY (or OPENROUTER_/ANTHROPIC_API_KEY). No key? Use
SIMPLICIO_MODEL=claude-cli/<model> or codex-cli/<model> to shell out to your logged-in CLI
```

Two offline fixes (PR #263):
- **Preferred (Q4 server):** set `SIMPLICIO_BASE_URL=http://127.0.0.1:11435/v1` and
  `SIMPLICIO_API_KEY=local-not-needed` (any non-empty value). The dev-cli then uses the
  OpenAI-compatible local server — no API key, no `--local`.
- **Fallback:** set `SIMPLICIO_MODEL=local/<anything>` so the loop appends `--local`.

When `SIMPLICIO_BASE_URL` is set, the loop does NOT append `--local` (it prefers the
OpenAI-compatible server). This is the right call for Q4 models.

## Trap 2 — `--local` needs llama-cpp-python AND uses MiniCPM5

With `--local` the dev-cli routes to a local llama.cpp backend and fails with:

```text
simplicio: local backend needs llama-cpp-python. Install extras: pip insta...
```

Fix: `python3 -m pip install llama-cpp-python`. BUT `--local` ignores `SIMPLICIO_BASE_URL`
and uses its own bundled **MiniCPM5 1.5B** model — too small to implement real code
(see Trap 4). Prefer the Q4-server path (Trap 1 preferred) instead.

## Trap 3 — `verification_command_missing`

The operator preflight fails with:

```text
blocked_preconditions: [{code: 'verification_command_missing',
  message: 'verification command missing; set SIMPLICIO_TEST_CMD before execution'}]
```

Set `SIMPLICIO_TEST_CMD` (or `SIMPLICIO_LOOP_TEST_CMD`) for the repo before the run:
- Python package: `SIMPLICIO_TEST_CMD="python -m pytest"` or `python -m unittest discover -s tests`
- Node/TS package: `SIMPLICIO_TEST_CMD="npm test"`
- Syntax-only fallback: `python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('pkg/**/*.py', recursive=True)]"`

## Trap 4 — small local model cannot implement complex code

A 1.5B (MiniCPM5) or even 3B (Qwen2.5-Coder-3B Q4) model generates a diff but the dev-cli
returns `applied: False` / `returncode: 1` / `rollback_reason: changed_paths_outside_checkpoint_scope`
after its <=3 retries. The model emits code in a shape the dev-cli patch parser rejects
(`parser_strategy: full_file_after_patch_failure`). This is a **MODEL-CAPABILITY limit**, not a
loop bug. A 7B+ Q4 model is needed for real TS/React/Python implementation.

Options to actually implement:
- Run a **7B+ Q4 GGUF** on the local `llama-server` (preferred — Q4 per user rule), OR
- Configure a real API backend (`codex-cli/<model>` or `claude-cli/<model>` with logged-in CLI), OR
- Accept the loop is functional end-to-end but cannot self-implement large issues on a <7B model.

Never mark an issue done on `applied: False`.

## Trap 5 — PATH resolves to a broken pipx wrapper (version probe fails)

`_resolved_identity("simplicio-dev-cli", ...)` uses `shutil.which` and picks the FIRST
`simplicio-dev-cli` on PATH. If `~/.local/bin` (pipx) precedes `/opt/homebrew/bin`, it grabs
`/Users/wesleysimplicio/.local/bin/simplicio-dev-cli` — a pipx wrapper that does
`from simplicio.cli import main` (the generic `simplicio` package, NOT `simplicio-py`). That
wrapper rejects `--version` with `rc=2` + `error: the following arguments are required: cmd`,
so the loop raises `simplicio-dev-cli version probe failed` even though the real binary works.

Symptom in `operator-preflight.json`: `"version_returncode": 2, "version_stdout": ""`.

**Fix:** force the real binary to the front of PATH for the loop run:

```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# verify: `which -a simplicio-dev-cli` should list /opt/homebrew/bin FIRST
/opt/homebrew/bin/simplicio-dev-cli --version   # -> simplicio-py 0.15.0
```

The genuine binary is `simplicio-py` (>=0.14.0); the pipx `simplicio.cli` homonym is a
decoy that passes the stem check but breaks `--version`.

## Trap 6 — local LLM LaunchAgent respawns the wrong model on port 11435

The `com.simplicio.local-llm` LaunchAgent keeps a `llama-server` alive on `127.0.0.1:11435`.
If you start a different-model server on that port, the agent respawns the OLD one (or the
port stays bound to 1.5B) and your Q4 model never takes effect.

**Fix before swapping the model:**

```bash
launchctl unload -w ~/Library/LaunchAgents/com.simplicio.local-llm.plist 2>/dev/null
lsof -ti:11435 | xargs kill -9 2>/dev/null
sleep 2
# now start the desired Q4 server via terminal(background=true):
/opt/homebrew/bin/llama-server -m Qwen2.5-Coder-3B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 11435 -c 8192 -b 128 -ub 32 --parallel 1 -t 4 \
  --n-gpu-layers 99 --mmap
# verify:
curl -s http://127.0.0.1:11435/v1/models | python3 -c "import sys,json;print([m['id'] for m in json.load(sys.stdin)['data']])"
```

Use `terminal(background=true)` for the server (not `nohup`/`&` in a foreground call — the
shell wrapper blocks it). Confirm the MODEL field shows your Q4 gguf, not the old 1.5B.

## Trap 7 — macOS has no GNU `timeout`

`timeout 180 cmd` fails with `timeout: command not found` on macOS. The loop uses Python
`subprocess.run(timeout=180)` internally (works), but if you reproduce preflight steps by hand,
use `subprocess.run(timeout=)` from Python or `terminal(background=true)` + `process(wait)`,
never the `timeout` wrapper.

## Verified sequence that got past ALL traps (canvas issue #67, Q4 server)

```bash
# 1. free port 11435 from the LaunchAgent's 1.5B server, start the Q4 model
launchctl unload -w ~/Library/LaunchAgents/com.simplicio.local-llm.plist 2>/dev/null
lsof -ti:11435 | xargs kill -9 2>/dev/null; sleep 2
# (start Qwen2.5-Coder-3B-Q4_K_M.gguf on 11435 via terminal(background=true), verify /v1/models)

# 2. run the loop with the REAL binary first on PATH + Q4 server env
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export SIMPLICIO_BASE_URL="http://127.0.0.1:11435/v1"
export SIMPLICIO_API_KEY="local-not-needed"
export SIMPLICIO_MODEL="Qwen2.5-Coder-3B"          # matches the server's model id
export SIMPLICIO_TEST_CMD="npm test"
export SIMPLICIO_LOOP_TEST_CMD="npm test"
cd <worktree>
/opt/homebrew/opt/python@3.11/bin/python3.11 -m simplicio_loop.cli run \
  --task .orchestrator/loop/task.md --repo . --max-iterations 3
```

Result observed: preflight passed (simplicio-py 0.15.0), operator executed against
`openai-compatible:127.0.0.1:11435`, `files_changed: ["src/main.ts"]` — but `applied: False`
on 3B (Trap 4). Swap to a 7B+ Q4 gguf on the same server to get real application.

Prereqs: `llama-server` + Q4 gguf available; loop package >= PR #263
(`fix/loop-mapper-freshness-path`); `/opt/homebrew/bin` ahead of `~/.local/bin` on PATH.
