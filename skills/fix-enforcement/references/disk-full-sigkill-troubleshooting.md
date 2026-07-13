# Disk Full → Simplicio SIGKILL Troubleshooting

## The Pattern

Simplicio crashes with **SIGKILL (-9, exit code 137)** when the system disk is
nearly full. This is **not** an enforcement issue — it's the kernel OOM killer
or filesystem allocator failing when Simplicio needs to allocate memory (swap)
or write temporary files.

**Key symptom:** `simplicio --version` or any non-trivial subcommand exits with
`Killed: 9` (macOS) or exit code 137 / SIGKILL.

## Diagnosis

```bash
df -h /
```

If **Available < 1GB**, disk pressure is very likely the cause. On macOS:
```bash
df -h /System/Volumes/Data
```
Often the Data volume fills up while the system volume looks fine.

## Quick Recovery

### 1. Kill the biggest cache offenders first

```bash
# Rust build artifacts (safest, biggest win)
cd ~/simplicio-runtime && cargo clean          # typically 3-7 GB

# Package manager caches
brew cleanup                                    # homebrew: 0.5-8 GB
uv cache clean                                  # python packages: 2-4 GB
npm cache clean --force                         # npm: 0.5-3 GB
pip cache purge                                 # python pip: 0.5-2 GB
```

### 2. Nuke cache directories (safe to recreate)

```bash
rm -rf ~/.cache/huggingface          # model weights, 5-15 GB
rm -rf ~/.cache/simplicio-runtime    # simplicio cache, 1-2 GB
rm -rf ~/.cache/codex-runtimes       # codex runtimes, 1-2 GB
rm -rf ~/.cache/puppeteer            # chromium downloads, 0.5-1 GB
rm -rf ~/.cache/opencode             # opencode cache, 0.2-1 GB
rm -rf ~/.cache/node                 # node cache, 0.1-1 GB
rm -rf ~/.npm                        # npm global cache, 0.5-3 GB
rm -rf ~/Library/Caches/ms-playwright    # browser binaries, 1-2 GB
rm -rf ~/Library/Caches/claude-cli-nodejs   # 0.5-1.5 GB
rm -rf ~/Library/Caches/Google/*     # chrome caches, 3-6 GB
rm -rf ~/.hermes/backups/*           # hermes backup tarballs, 2-4 GB
```

### 3. Verify recovery

```bash
df -h /System/Volumes/Data           # should show >5 GB available
simplicio help                        # should work without SIGKILL
simplicio doctor                      # full health check
```

## When `simplicio runtime-profile` Also Crashes

If changing the profile via `simplicio runtime-profile use normal` also
SIGKILLs, edit the config file directly:

```bash
# In ~/.simplicio/runtime.toml:
# Change: default_profile = "full"  →  default_profile = "normal"
```

```toml
[runtime]
default_profile = "normal"
offline_first = true
```

This avoids loading the model/runtime just to change the profile.

## Prevention

- Run `brew cleanup` periodically (weekly cron)
- Run `cargo clean` after major Rust builds
- Set `default_profile = "normal"` in `~/.simplicio/runtime.toml` to reduce
  memory pressure (profile=full uses 2GB KV cache; normal uses 512MB)
- Monitor disk with `df -h` when Simplicio starts behaving erratically
