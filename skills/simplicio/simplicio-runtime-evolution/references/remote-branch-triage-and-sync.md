# Remote branch triage, lossless main sync, cherry-pick (2026-07-08)

Session-verified recipes for answering "what do other bots' branches have?" and syncing `main` without losing local or remote work.

## Lossless `git pull` on `main`

When the user asks to update `main` without losing **remote** or **local** uncommitted work:

```bash
cd <repo>
git stash push -u -m "lossless-sync-$(date +%F)"
git fetch origin
git checkout main
git pull --ff-only origin main
git stash pop
git rev-parse main origin/main   # SHAs must match
```

- **`--ff-only`**: never rewrite history; if it fails, `main` diverged — rebase/merge explicitly, do not force.
- If `stash pop` conflicts (e.g. orchestrator jsonl logs), **union** log lines; never discard unrelated code.
- Pre-existing dirty files: stash may report "No local changes" if another process already committed or cleaned — re-check `git status` before assuming loss.

## Auditing a remote feature branch vs `main`

```bash
git fetch origin
git rev-list --left-right --count main...origin/<branch>   # A B = commits only on main / only on branch
git merge-base --is-ancestor origin/<branch> main && echo ancestral
git log --oneline main..origin/<branch>                      # branch-only commits
git log --oneline origin/<branch>..main | head -20           # main-only commits (do not lose on merge)
git diff --stat main...origin/<branch>
```

| Signal | Meaning | Action |
|--------|---------|--------|
| `0` commits on branch side, branch ancestral | Stale snapshot | Delete remote branch after `gh pr list` shows no open PRs |
| Both sides have unique commits | **Diverged** | **No blind merge** — cherry-pick or reconcile per commit |
| Adapter/path fix already on `main` | Cherry-pick may be **empty** | `git cherry-pick --skip` and cite equivalent merge (e.g. `#2976`) |

## Cherry-pick loop (skip empty)

```bash
for c in <sha1> <sha2> ...; do
  git cherry-pick -x "$c" || {
    git status | grep -q "nothing to commit" && git cherry-pick --skip && continue
    git cherry-pick --abort; exit 1
  }
done
```

Empty cherry-picks often mean **`main` already absorbed** the work via a different PR number — close the tracking issue with evidence (`git log --oneline` + PR link), not a no-op narrative.

## `simplicio wormhole` after source exists

Routing lives in `src/commands/mod.rs` (`wormhole` | `wh`). Verify on **fresh release build**, not only installed PATH binary:

```bash
cd simplicio-runtime
cargo build --release
./target/release/simplicio wormhole    # prints Usage (send/receive/traverse)
```

- `./target/release/simplicio wormhole help` may route incorrectly on some builds; default `wormhole` with no subcommand is the smoke test.
- Copying to `~/.local/bin/simplicio` on macOS may yield **Killed:9** (unsigned binary) — use `target/release` path or `codesign`.

## `doctor`: `simplicio-prompt` incompatible

Often **version matrix mismatch**, not a missing binary:

- Matrix `minimum_version`: e.g. `1.14.1`
- Detected package version: e.g. `0.24.0` (same commit SHA possible)

Fix paths: align `minimum_version` in runtime compatibility matrix **or** upgrade/publish `simplicio-prompt` declaring `simplicio.context-cache/v1`. Do not close as "doctor green" until `compatibility.components[]` shows `status: compatible` or a documented waiver issue remains open.

## Delete obsolete remote branch (API)

After `gh pr list --search "<branch-name>"` returns empty:

```bash
gh api -X DELETE "repos/<owner>/<repo>/git/refs/heads/<branch>"
```

Evidence: `git ls-remote --heads origin <branch>` returns nothing.