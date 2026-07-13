# PR #104 / fast stack — verification checklist

Use when the user asks whether PR #104 (or "fast stack") changes are **applied**. Report three layers separately.

## Layer 1 — Git (code on branch)

```bash
cd /path/to/simplicio-agent
git fetch origin main -q
git merge-base --is-ancestor 24da876c32345fbdc9c91a53d677847bf3ab5953 HEAD \
  && echo "PR104 merge in HEAD: YES" || echo "PR104 merge in HEAD: NO"
git status -sb   # expect clean or only intentional local edits
```

PR #104 title: `feat(identity+perf): simplicio-agent as canonical command; fast stack default-on (wave 1)`.

## Layer 2 — Venv (hermes_fast built)

Always use **checkout venv**, not bare Homebrew Python:

```bash
cd /path/to/simplicio-agent
.venv/bin/python -c "
from agent._hermes_fast import HAVE_RUST
import importlib.util as u
for m in ['orjson','msgspec','uvloop','tiktoken','h2','hermes_fast']:
    print(m, 'ON' if u.find_spec(m) else 'OFF')
print('HAVE_RUST', HAVE_RUST)
"
```

If `hermes_fast OFF` or `HAVE_RUST False`:

```bash
bash scripts/build_fast_stack.sh
```

## Layer 3 — Supervised gateway (Discord / launchd)

After any `maturin develop`, restart **outside** the gateway chat session:

```bash
simplicio-agent gateway restart
```

LaunchAgent label on Wesley's Mac: `ai.hermes.gateway-simplicio-agent` → `~/.simplicio_agent/bin/start-simplicio-agent-discord.sh` (uses `.venv/bin/python`).

**Blocked from inside gateway:** attempting `gateway restart` from the bot process fails by design (SIGTERM to children).

## Post-merge hook (local only)

```bash
cp scripts/git-hooks/post-merge-fast-stack .git/hooks/post-merge
chmod +x .git/hooks/post-merge
```

Rebuild runs automatically when a pull/merge touches `rust_ext/`.

## User-facing answer template (pt-BR)

1. **No git:** sim — commit da PR na `main`.
2. **No venv:** sim/não — medir com probe; se OFF, rodar `build_fast_stack.sh`.
3. **No gateway:** reinício externo necessário após build; não dá da sessão do bot.