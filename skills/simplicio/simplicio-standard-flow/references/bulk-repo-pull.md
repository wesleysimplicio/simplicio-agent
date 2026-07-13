# Bulk git pull across ~/Projetos/ai

Reusable recipe to pull (fast-forward only) every git repo under a directory
while skipping plain dirs and branches with no upstream tracking.

## Why
When asked to "pull all projects", naive `git pull` in every subdir fails on
non-git folders and on branches without a configured upstream. Use `--ff-only`
so divergent histories error loudly instead of creating merges.

## Recipe (run as a script, not inline — avoids quoting pain)
```bash
#!/usr/bin/env bash
set -uo pipefail
OUT=/tmp/pull_all_$(date +%s).log
: > "$OUT"
for d in /Users/wesleysimplicio/Projetos/ai/*/; do
  name=$(basename "$d")
  if [ -d "${d}.git" ]; then
    branch=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)
    upstream=$(git -C "$d" rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo NONE)
    echo "=== $name (branch=$branch upstream=$upstream) ===" >> "$OUT"
    if [ "$upstream" = NONE ]; then
      echo "  no upstream tracking branch — skipping pull" >> "$OUT"
    else
      git -C "$d" pull --ff-only 2>&1 | tail -4 >> "$OUT"
    fi
  else
    echo "=== $name === NOT A GIT REPO" >> "$OUT"
  fi
done
cat "$OUT"
```

## Notes
- Write the loop to a file and `bash` it (simplicio shell quoting mangles `for d in */` variable expansion).
- `--ff-only` prevents accidental merges on diverged branches.
- A branch with no upstream (e.g. `fix/...` not pushed) is reported, not errored.
- Clean up the temp script after (don't leave `_pull_all.sh` in the repo).
