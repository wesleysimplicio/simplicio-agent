# Local Runtime Release (rebuild + reinstall adapters + verify)

Verified recipe from the 2026-07-09 session: align 10 `~/Projetos/ai` repos,
commit local working-tree changes past the pre-commit gate, rebuild the Rust
binary, reinstall the Python adapters from their pull'd checkouts, and prove
the runtime works with `doctor --json` + `runtime smoke --json`.

## When this applies
- After `git pull` landed a new runtime version (e.g. v3.4.0 -> v3.5.0) and the
  installed binary is now stale.
- After local edits to `simplicio-runtime` that must ship locally.
- Periodically, to keep binary + adapters in lockstep with `main`.

## Command sequence
```bash
cd ~/Projetos/ai/simplicio-runtime

# 1. Orient + recall + state (parallel)
simplicio runtime map --repo . --for-llm markdown
simplicio memory "<topic>"
simplicio doctor --json          # capture CURRENT version vs source

# 2. Pull all sibling repos (ff-only; reject if rejects)
for r in ~/Projetos/ai/*/; do (cd "$r" && git pull --ff-only); done

# 3. Commit local working-tree changes (see gate below), then push main
git add <explicit files>         # NEVER `git add -A`
git commit -m "chore: align local tree to vX.Y.Z baseline"
git push origin main

# 4. Rebuild the binary (release + rich-repl; ~5min on 8GB mac)
cargo build --release --features rich-repl
cp -f target/release/simplicio ~/.local/bin/simplicio
cp -f target/release/simplicio /opt/homebrew/bin/simplicio
./target/release/simplicio version   # must print new version

# 5. Reinstall Python adapters from their checkouts (see pip trap below)
for p in simplicio-mapper simplicio-dev-cli simplicio-loop; do
  (cd ~/Projetos/ai/$p && /opt/homebrew/bin/python3.11 -m pip install -e .)
done

# 6. Verify
simplicio doctor --json          # overall_status: "ok", compatibility compatible
simplicio runtime smoke --json   # status: "passed"
```

## Pitfall: pre-commit gate "script ownership inventory stale"
The runtime's `hooks/` pre-commit runs a self-review + ownership audit. After a
version pull that adds new `scripts/`, the gate fails HIGH with:
`script ownership inventory/doc is stale. run py scripts/audit-script-ownership.py`.
FIX (do not skip):
```bash
python3 scripts/audit-script-ownership.py
git add docs/SCRIPT_OWNERSHIP_QUARANTINE.md .simplicio/docs/script-ownership-inventory.json
# then re-stage your real change files and commit
```
If the gate ALSO flags false-positive "secret" lines inside the generated
inventory JSON (they are script paths, not creds), the commit still proceeds -
read the lines before reaching for `SIMPLICIO_GATE_SKIP=1`. Only skip when it is
genuinely the bot's own safe change and you have verified the flagged lines.

## Pitfall: macOS `pip3` is Python 3.9.6 (too old)
System `pip3`/`python3` is 3.9.6; runtime adapters require `>=3.10`. Installing
with `pip3 install -e .` fails: `requires a different Python: 3.9.6 not in '>=3.10'`.
FIX: use the Homebrew Python 3.11 that already feeds `/opt/homebrew/bin`:
```bash
/opt/homebrew/bin/python3.11 -m pip install -e .
```
(verify with `which -a python3.11` -> `/opt/homebrew/bin/python3.11`.)

## Pitfall: no `timeout` command on macOS
`timeout 120 cmd` -> `command not found`. Run the command directly (the process
tool or a plain foreground `terminal` call handles long jobs; for cargo builds
use `terminal(background=true, notify_on_complete=true)` and `process(wait)`).

## Pitfall: adapters resolve on PATH, not the cargo target
`doctor` looks for `simplicio-mapper`, `simplicio-py` (dev-cli), `simplicio-loop`,
`simplicio-subagents` (prompt) on PATH. After reinstall, confirm:
```bash
/opt/homebrew/bin/simplicio-mapper --version   # 0.19.0
/opt/homebrew/bin/simplicio-py --version
/opt/homebrew/bin/simplicio-loop --version     # 3.24.0
```

## Evidence bar (what "done" means)
- `doctor --json` -> `"overall_status":"ok"`, `"health":{"overall":"ok"}`,
  all 5 adapters `available`, `compatibility` gate `compatible`, MCP registered.
- `runtime smoke --json` -> `"status":"passed"` (9 checks green: mapper/dev-cli/
  prompt/loop/llama-server + runtime self-check).
- `simplicio version` prints the new version from BOTH `~/.local/bin` and
  `/opt/homebrew/bin`.
