---
name: simplicio-agent-fast-stack
description: Activate and verify the Simplicio Agent fast stack and macOS resource bottlenecks. Load for performance, slowness, PR #104, hermes_fast, or OS-level gargalo on 8GB Macs. PERFORMANCE not layout.
---

# Simplicio Agent — Fast Stack Activation & Verification

## When to use
- User reports the agent feels slower than "Hermes normal" / upstream.
- User asks about `simplicio-agent` performance (PR #104: "fast stack default-on").
- User asks for **OS / macOS bottleneck** ("gargalo no sistema", machine sluggish globally).
- After `git pull` / fresh clone that may have touched `rust_ext/`.
- `simplicio-agent doctor` shows "Rust hot-path extension (hermes_fast)" as unavailable.

## Agent fast stack vs macOS resource pressure
When the user says **lento**, run in order:
1. **Agent layer** — fast-stack probe + `doctor` Performance Modules. If `HAVE_RUST` is False → `scripts/build_fast_stack.sh` + external gateway restart; stop if that was the only gap.
2. **OS layer** — if probe is fully ON but UX still bad: RAM/swap/load (`scripts/os-pressure-probe.sh`). On **8 GB** Macs, swap + `cargo build --release` (watch-release) often dominate; fixing `hermes_fast` does not help.

See `references/macos-resource-pressure.md` for launchd labels and relief commands.

## CRITICAL DISCIPLINE — PERFORMANCE, NOT LAYOUT
When the user says "performance" / "mais lento" / "foi na PR X de performance", DO NOT spend turns on
branding / banner / wordmark / TUI layout diffs. Go straight to the performance modules. The user has
explicitly rejected layout-focused investigation ("nao estou falando de layout, estou dizendo de
performance"). Banner/branding changes are NOT the performance story — they are rebrand noise that
dominates the diff stat but contributes ~0 to latency.

## What the fast stack is (from docs/performance.md)
Additive, degrades gracefully. On by default with the installer `[all]` tier; on a SOURCE CHECKOUT you
must ensure the deps are installed AND build the Rust ext yourself — otherwise it silently falls back to
pure-Python (the "slower than Hermes" symptom).

| Layer | Module | Check | Enable |
|---|---|---|---|
| fast JSON | orjson / msgspec | `import orjson` | `pip install "hermes-agent[fast]"` |
| fast loop | uvloop | `import uvloop` | `pip install "hermes-agent[fast]"` (no-op on Windows) |
| **Rust hot path** | hermes_fast (rust_ext) | `from agent._hermes_fast import HAVE_RUST` | **build with maturin** |
| token estimate | tiktoken | `import tiktoken` | `pip install tiktoken` |
| HTTP/2 | h2 | `import h2` | `pip install "httpx[http2]"` |

The biggest win is **hermes_fast** (PyO3 Rust): `estimate_tokens`, `estimate_messages_tokens`,
`parse_tool_call_delta`, `truncate_messages_to_limit`. It is MISSING by default on a source checkout
unless you build it. This is the #1 cause of "slower than Hermes" on a dev machine.

## Three layers when user asks "colocou as modificações da PR #104?" (or similar)
Answer with **three separate checks** — never conflate "merged on main" with "fast stack live in Discord":

| Layer | What it means | How to verify |
|---|---|---|
| **1. Git** | PR #104 merge commit is in `HEAD` | `git merge-base --is-ancestor <merge-oid> HEAD` (simplicio-agent #104 ≈ `24da876c3`) |
| **2. Venv** | `hermes_fast` built into checkout `.venv` | `.venv/bin/python` + probe → `HAVE_RUST True` and all six modules ON |
| **3. Running gateway** | Long-lived launchd/supervised process loaded the ext | Restart required after maturin build; **cannot** `gateway restart` from inside the gateway session |

Layer 1 can be YES while layer 3 is still stale (process started before `maturin develop`). Tell the user to run `simplicio-agent gateway restart` from a **separate shell** (or restart LaunchAgent `ai.hermes.gateway-simplicio-agent`). Launchd on this host uses `~/.simplicio_agent/bin/start-simplicio-agent-discord.sh` → `.venv/bin/python` — but only a restart picks up a newly built extension.

### Supervision verification before claiming Discord is up
A successful CLI return is not proof that the Discord bot is connected. Verify all three independently:
1. `launchctl list` contains the expected Simplicio label and `launchctl print gui/$(id -u)/<label>` reports `state = running` with a current PID.
2. `simplicio-agent gateway status` agrees that the supervised process is active; distinguish a detached/manual PID from launchd supervision.
3. Gateway logs or a Discord gateway/API probe show a real connection/ready event. If DNS or Discord gateway resolution fails, report the process as **running but Discord connectivity UNVERIFIED**, never as logged in.

If `gateway start` targets a stale/legacy label while the Simplicio plist uses `ai.hermes.gateway-simplicio-agent`, do not retry blindly. Stop the detached process if present, validate the plist with `plutil -lint`, then bootstrap the exact plist with `launchctl bootstrap gui/$(id -u) <plist>`. Re-check launchd state and logs after bootstrap. This recovery is for label/config drift; it does not bypass a genuine Discord network failure.

**Note:** `.venv/bin/python` often symlinks to Homebrew `python3.11`; site-packages still live under `.venv`. Probing bare `opt/homebrew/.../Python` without the venv on `PATH` falsely shows `hermes_fast OFF`.

## Verify what is ACTUALLY ON (run the probe, don't assume)
Run `references/fast-stack-probe.py` from the repo root with the venv python:
```bash
.venv/bin/python ~/.simplicio_agent/skills/simplicio-agent-fast-stack/references/fast-stack-probe.py
```
Or inline:
```python
from agent._hermes_fast import HAVE_RUST
import importlib.util as u
for m in ['orjson','msgspec','uvloop','tiktoken','h2','hermes_fast']:
    print(m, 'ON' if u.find_spec(m) else 'OFF')
print('HAVE_RUST', HAVE_RUST)
```
Also check boot-slim: `hermes_cli.config` must NOT be a top-level import in `hermes_cli/main.py`
(the cold-import win comes from keeping that ~100ms module out of boot). Confirm with:
`time (.venv/bin/python -c "import hermes_cli.main")`.

## Activation recipe (source checkout)
**Preferred:** repo script (on `main` since 2026-07-08):
```bash
cd ~/Projetos/ai/simplicio-agent   # or your checkout
bash scripts/build_fast_stack.sh
```

**Manual equivalent** (if script missing on an old checkout):
```bash
.venv/bin/python -m pip install maturin tiktoken h2
cd rust_ext && ../.venv/bin/python -m maturin develop
```

After: `HAVE_RUST` becomes True; orjson yields ~11x stdlib on the json.dumps hot path. Then **restart the supervised gateway** (see three-layer table above).

## Post-pull / post-merge (PR #104 rust_ext)
- Repo: `scripts/git-hooks/post-merge-fast-stack` — rebuilds only when `rust_ext/` changed in the merge.
- **Local install (not committed):** `cp scripts/git-hooks/post-merge-fast-stack .git/hooks/post-merge && chmod +x .git/hooks/post-merge`
- Managed simplicio-agent repo: use `simplicio edit` / terminal for file writes; Hermes `write_file`/`patch` may be blocked — use `bash scripts/build_fast_stack.sh` after pull if hook not installed.

See `references/pr104-verification.md` for a copy-paste checklist.

### Repository-sync provenance gate
A successful `git fetch` is not the same as a working-tree update, and a local checkout is not the same as the installed operator. After syncing `~/Projetos/ai`:
1. Inventory every repo, current branch, dirty count, and remote URL.
2. For clean repos on `main`/`master`, run `git pull --ff-only origin <branch>`.
3. For dirty repos or active worktrees, do not stash/reset/force-update automatically; run `git fetch --prune origin`, record `origin/main`/`origin/master`, and preserve the working branch.
4. Compare installed versions (`simplicio`, mapper, dev-cli, loop) with local checkout/release metadata before claiming the latest code is active. Pulled source does not update installed binaries.
5. Run `simplicio doctor --json`, the fast-stack probe, and `simplicio contracts smoke --json`; report missing artifacts separately from adapter/runtime failures.
6. If smoke fails, keep the result `UNVERIFIED` until the named artifact and expected repo root are verified. Never summarize a partial sync as “everything updated”.

See `references/repository-sync-provenance.md` for the compact recipe and evidence table.

## Pitfalls
- **Don't read the branding diff for perf questions.** PR #104's `git show --stat` is ~80% rebrand
  string changes across READMEs/issue templates. The perf substance lives in `rust_ext/`,
  `hermes_cli/container_boot.py`, `run_agent.py`, and the lazy `hermes_cli.config` import in
  `hermes_cli/main.py`. Grep the perf files, skip the banner files.
- **hermes_fast `estimate_messages_tokens`:** pass a **list of message dicts**, not a JSON string (the Rust path serializes internally).
- **Upstream benchmark needs a sibling checkout.** `scripts/benchmark_vs_upstream.py` errors with
  "`.../hermes-agent does not look like a hermes-agent checkout`" unless `../hermes-agent` exists.
  Measure locally instead (orjson vs stdlib json.dumps; presence of the Rust path).
- **Rebuild after every pull that touches rust_ext/.** maturin-built ext silently falls back to
  pure-Python if `rust_ext/` changed and you didn't rebuild — the slowness returns with no error.
  Use post-merge hook or `bash scripts/build_fast_stack.sh` after pulls.
- **Gateway restart from inside the bot:** `simplicio-agent gateway restart` is blocked when the
  current session *is* the gateway ("SIGTERM propagates to child processes"). Document the external
  restart; do not loop retries from Discord/chat.
- **Writes in simplicio-agent checkout:** Simplicio sandbox may block Hermes native `write_file`/`patch`;
  use terminal or `simplicio edit --plan` for `scripts/build_fast_stack.sh` and hook files.
- **micro-benchmark artifact:** measuring `estimate_messages_tokens` on tiny synthetic 200-msg lists can
  show Rust "slower" than the `len//4` fallback because of PyO3 str-serialize overhead. That is a
  benchmark artifact, NOT a real regression — the Rust path wins on real streaming/truncate workloads.

## Standing mandate (Wesley 2026-07-08)
**Always keep Simplicio Agent fast and token-economical.** Do not regress to pure-Python fallback.
After any `git pull` touching `rust_ext/`: run `bash scripts/build_fast_stack.sh` and restart supervised gateway.
On **8 GB Mac**: `simplicio runtime-profile use low`; avoid background release builds + dual LLM + dual gateway during daily use.
Cron: `fast-stack-watchdog` every 6h (silent when OK; alerts on Discord when a layer is OFF).

## Evidence (2026-07-08, this MacBook)
- BEFORE: hermes_fast MISSING → pure-Python fallback ("slower than Hermes").
- AFTER build: HAVE_RUST=True; all 6 layers ON; orjson ~10x stdlib on json hot path.
- OS (same session): 8 GB RAM, swap ~1.2 GB, load 56 — **gargalo was memory + `cargo release` + Gemma llama `-c 65536`**, not fast stack. Relief: bootout `com.simplicio.runtime.watch`, bootout `com.wesleysimplicio.llama-gemma4`, `runtime-profile low`.

## Support files
- `references/fast-stack-probe.py` — agent-layer probe.
- `references/pr104-verification.md` — git / venv / gateway checklist.
- `references/macos-resource-pressure.md` — OS bottleneck playbook.
- `scripts/os-pressure-probe.sh` — macOS snapshot (load, swap, llama/cargo/gateways).
- `scripts/build_fast_stack.sh` — activator; canonical copy in simplicio-agent `scripts/build_fast_stack.sh`.
