# Release v1.0.4 — Public Dist Repo Sync

**Date:** 20/Jun/2026
**Release assets:** simplicio-darwin-arm64, simplicio-darwin-x64, simplicio-linux-x64, simplicio-windows-x64
**GitHub release:** https://github.com/wesleysimplicio/simplicio/releases/tag/v1.0.4

## What was done

Synced the public distribution repo (`~/simplicio/` — master branch) to match the v1.0.4 GitHub release.

### Files updated
- `VERSION.md` → v1.0.4
- `simplicio-update-manifest.json` → v1.0.4 with new SHA256s for macos-arm64 + windows-x64
- `Formula/simplicio.rb` → v1.0.4, SHA: `36dd2cbb21ecd7ac2bdd944dd0f90b051b8db6d6d6b4eb736a2906f533f74b55`
- `npm/simplicio/package.json` → v1.0.4 (version bump only — no npm publish per user preference)
- `pypi/simplicio/pyproject.toml` → v1.0.4
- `SHA256SUMS` → updated checksums
- `.gitignore` → added `*.egg-info/`
- Binary: `simplicio` (macOS ARM64, 18.5MB, v1.0.4)
- Binary: `simplicio.exe` (Windows x64, 21.8MB)

### Files removed
- `simplicio-windows-x86_64.exe` (old naming, replaced by `simplicio.exe`)

### PyPI published
- Package: `simplicio-installer` v1.0.4
- Published via `python3 -m build && twine upload dist/*`
- Verify: `curl -s https://pypi.org/pypi/simplicio-installer/1.0.4/json`

### Git
- Remote URL updated: `Simplicio.git` → `simplicio.git` (case change)
- Commit: `71d525c` — `release v1.0.4: update macOS/Windows binaries, npm, PyPI, Homebrew packages`
- Pushed after `git pull --rebase` (remote had 4 ahead commits)

### What was NOT published
- npm was skipped (user said "npm não precisa")
- Homebrew formula was updated in repo but formula publish/tap not done
- Site FTP deploy was not needed (install.sh fetches from GitHub releases/latest)

## Binary naming cross-reference
| Channel | Name for macOS ARM64 |
|---------|---------------------|
| GitHub Release asset | `simplicio-darwin-arm64` |
| Repo root (raw) | `simplicio` |
| Update manifest | `simplicio` (target: `macos-arm64`) |
| Site dist/ | `simplicio-darwin-arm64` (historical, may not be current) |
| Homebrew formula | `simplicio` (raw from master) |
