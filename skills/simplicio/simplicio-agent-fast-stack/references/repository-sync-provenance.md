# Repository-sync provenance reference

Use this after updating multiple Simplicio repositories.

## Evidence sequence

```bash
cd ~/Projetos/ai
for d in */.git; do
  repo=${d%/.git}
  git -C "$repo" branch --show-current
  git -C "$repo" status --porcelain
  git -C "$repo" remote get-url origin
 done
```

Then, in parallel where independent:

```bash
# clean default branches only
git -C <repo> pull --ff-only origin main   # or master

# dirty repos / active worktrees
git -C <repo> fetch --prune origin
```

Never reset, force-update a branch used by another worktree, or stash unresolved conflicts automatically. A fetch updates remote refs only; it does not update the checked-out branch. A source checkout update also does not update installed Python/Rust operators.

## Required post-sync checks

```bash
simplicio doctor --json
simplicio contracts smoke --json
# fast-stack probe from the agent checkout
.venv/bin/python - <<'PY'
import importlib.util
for name in ('orjson','msgspec','uvloop','tiktoken','h2','agent._hermes_fast'):
    print(name, 'ON' if importlib.util.find_spec(name) else 'OFF')
from agent._hermes_fast import HAVE_RUST
print('HAVE_RUST', HAVE_RUST)
PY
```

Report separately:
- Git state: pulled, fetched-only, or blocked by dirty/worktree state;
- Installed operator state versus local checkout/release state;
- Runtime/adapter health;
- Smoke-test artifact failures.

Do not claim “all projects updated” unless every intended default branch was pulled or its exact reason for fetch-only status is stated.
