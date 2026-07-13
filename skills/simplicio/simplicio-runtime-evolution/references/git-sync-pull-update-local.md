# Pull remote `main` → update local Simplicio agent + runtime

Use when the user says: *modificamos a main remota, traz pro local e atualize*.

## Preconditions
- Sibling checkouts: `~/Projetos/ai/simplicio-agent`, `~/Projetos/ai/simplicio-runtime`
- Global binary: `~/.local/bin/simplicio` (not only repo `target/release`)
- On **8 GB Mac**: expect `cargo build --release` ~4–15 min; avoid `com.simplicio.runtime.watch` during interactive use.

## Recipe (verified 2026-07-09)

```bash
# 1) Agent
cd ~/Projetos/ai/simplicio-agent
git fetch origin main
git pull --ff-only origin main
git log -1 --oneline
.venv/bin/python -m pip install -e ".[fast]" -q
bash scripts/build_fast_stack.sh
.venv/bin/python -m pytest tests/tools/test_kernel_binding.py -q --tb=no   # when kernel_binding changed

# 2) Runtime
cd ~/Projetos/ai/simplicio-runtime
git fetch origin main
git pull --ff-only origin main
git log -1 --oneline
cargo build --release --locked
cp target/release/simplicio ~/.local/bin/simplicio && chmod +x ~/.local/bin/simplicio

# 3) Runtime health (MCP/CLI)
simplicio validate --repo ~/Projetos/ai/simplicio-runtime
simplicio doctor --json

# 4) Optional: simplicio neural store — sync fact (agent HEAD, runtime HEAD)
```

## After pull — gateway
- **Agent code** (editable install): gateway picks up Python on **next process start** only.
- **`kernel_binding` / warm MCP** (#109): restart **outside** bot session:
  `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway-simplicio-agent`
- Blocked from inside Discord: `simplicio-agent gateway restart`.

## Local dirt on runtime
Modified files **after** ff-only pull = local edits, not failed pull.

## Managed-repo writes
Hermes `write_file`/`patch` may be blocked in `simplicio-agent` — use `simplicio edit --plan` or terminal.

## Evidence to report (pt-BR)
| Repo | HEAD | Pull |
|------|------|------|
| simplicio-agent | e.g. `642fb67f2` | ff-only |
| simplicio-runtime | e.g. `c141c1b6` | ff-only |
| `~/.local/bin/simplicio` | mtime + size after `cp` | MEASURED|