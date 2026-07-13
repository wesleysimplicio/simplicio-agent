---
name: macos-disk-recovery-and-simplicio-reinstall
description: "Recover from full-disk conditions (SIGKILL) on macOS and perform a clean reinstall of Simplicio Runtime from scratch — cloning, building, installing binaries, model download, Hermes plugin wiring."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [simplicio, disk-recovery, macos, install, maintenance, rust]
    related_skills: [simplicio-release-operations, rust-patterns]
---

# macOS Disk Recovery & Simplicio Runtime Reinstall

## Disk Space Recovery

### SIGKILL Diagnostic

If Simplicio (or any binary) crashes with `Killed: 9` (SIGKILL -9) immediately
on launch, the most likely cause is **disk at 100% capacity**. macOS kills
processes when the kernel cannot allocate swap, temp files, or page memory.

Check both the system and writable Data volume on APFS:
```bash
df -h / /System/Volumes/Data
```

If available space is < 1GB, treat disk pressure as the root cause before builds,
mapper/index jobs, SQLite/WAL work, or benchmarks.

### Surgical removal of a user-named directory

When the user explicitly names a directory to delete, do **not** replace it with
broad cache cleanup. First resolve the exact path, then measure and remove only
that path, and verify it disappeared plus the reclaimed space. Use a guarded
one-shot command so a typo cannot expand the scope:

```bash
TARGET="$HOME/Projetos/ai/<user-named-directory>"
EXPECTED_PARENT="$HOME/Projetos/ai"
set -euo pipefail
[ "$(dirname "$TARGET")" = "$EXPECTED_PARENT" ]
[ -d "$TARGET" ]
du -sh "$TARGET"
df -h /System/Volumes/Data
rm -rf -- "$TARGET"
[ ! -e "$TARGET" ]
df -h /System/Volumes/Data
```

If name lookup returns no exact directory, search spelling variants and parent
locations; do not delete a similarly named file, cached transcript, runtime
release, or worktree merely to satisfy the request.

### Common macOS Space Hogs

| Item | Typical size | Cleanup |
|------|-------------|---------|
| `~/.cache/huggingface` | 5-10GB | `rm -rf ~/.cache/huggingface` |
| `~/Library/Caches/Homebrew` | 6-8GB | `brew cleanup` |
| `~/.cache/uv` | 3-4GB | `uv cache clean` |
| `~/.npm` | 0.5-2GB | `npm cache clean --force && rm -rf ~/.npm` |
| `~/Library/Caches/Google` | 3-6GB | `rm -rf ~/Library/Caches/Google/*` |
| `~/Library/Caches/ms-playwright` | 1-2GB | `rm -rf ~/Library/Caches/ms-playwright` |
| `~/.cache/puppeteer` | 1-2GB | `rm -rf ~/.cache/puppeteer` |
| `~/.cache/simplicio-runtime` | 1-2GB | `rm -rf ~/.cache/simplicio-runtime` |
| `~/.hermes/backups` | 2-4GB | `rm -rf ~/.hermes/backups/*` |
| Rust `target/` dirs | 2-4GB each | `cargo clean` per project |
| `pip cache` | 0.5-2GB | `pip cache purge` |

Strategy: clean all caches in one pass, then verify with `df -h /`.

### Build crashes from full disk

If `cargo build` fails with "No space left on device" on the temp files, it is
the SAME root cause — there isn't even space for shell temp files. Clean disk
first, then retry.

---

## Full Clean Reinstall of Simplicio Runtime

Use this when you need to nuke everything and start fresh.

### Step 1: Uninstall

```bash
# Remove binaries
rm -v ~/.local/bin/simplicio ~/.local/bin/simplicio-mapper 2>/dev/null
rm -v ~/.cargo/bin/simplicio 2>/dev/null
ls ~/.local/bin/simplicio*  # inspect before removing

# Remove runtime data
rm -rf ~/.simplicio

# Remove source repos
rm -rf ~/Projetos/ai/simplicio-runtime
# Also check ~/simplicio-runtime for additional copies

# Remove caches
rm -rf ~/.cache/simplicio-runtime

# Disable Hermes plugin
hermes config set plugins.enabled '[]'
hermes config set plugins.disabled '["simplicio"]'
```

### Step 2: Clone & Build

```bash
mkdir -p ~/Projetos/ai
cd ~/Projetos/ai
git clone https://github.com/wesleysimplicio/simplicio-runtime.git
cd simplicio-runtime
git config core.hooksPath hooks
cargo build --release
# → ~5 min first build
```

### Step 3: Install Binary

```bash
cp target/release/simplicio ~/.local/bin/simplicio
ln -sf ~/.local/bin/simplicio ~/.cargo/bin/simplicio 2>/dev/null
chmod +x ~/.local/bin/simplicio
simplicio version  # verify
```

### Step 4: Download GGUF Model

The local inference model (1.27 GB for Q6_K_L):

```bash
mkdir -p ~/.simplicio/models
curl -L -o ~/.simplicio/models/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf \
  "https://huggingface.co/bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf"
```

### Step 5: Fix Model Path

`simplicio doctor` checks both global (`~/.simplicio/models/`) and
project-local (`<repo>/.simplicio/models/`) paths. If doctor reports the
model absent but you downloaded it globally, create a symlink:

```bash
mkdir -p ~/Projetos/ai/simplicio-runtime/.simplicio/models
ln -sf ~/.simplicio/models/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf \
  ~/Projetos/ai/simplicio-runtime/.simplicio/models/
```

### Step 6: Install Python Adapter

```bash
pip3 install --upgrade simplicio-cli
ln -sf ~/Library/Python/3.9/bin/simplicio ~/.local/bin/simplicio-py
```

### Step 7: Re-enable Hermes Plugin

```bash
hermes config set plugins.enabled '["simplicio"]'
hermes config set plugins.disabled '[]'
```

### Step 8: Verify

```bash
simplicio doctor
# Expected: health: ok (all green)
```

### Set profile (optional)

```bash
# Default is "normal" (128 agents, 512MB KV cache)
# Write directly to runtime.toml if `simplicio runtime-profile use` SIGKILLs:
#   [runtime]
#   default_profile = "normal"
```

## Pitfalls

- **Site submodule detached HEAD**: After `git submodule update`, the submodule
  is in detached HEAD. Create a branch before committing.
- **Dist/ binaries gitignored**: Force-add with `git add -f` in the site submodule.
- **Hermes config is protected**: Use `hermes config set` not direct file edit.
- **Calling `cd ~/deleted-repo`**: After deleting the repo you were cd'd into,
  the shell cwd is invalid. Fix with `cd ~` or `cd /` before running commands.
