# Release v1.2.0 — Universal Adapter + Pre/Post Hooks

**Date:** 2026-06-20  
**Runtime version:** `Cargo.toml` → 1.2.0, tag `v1.2.0`  
**Runtime repo:** simplicio-runtime (private)  
**Distro repo:** wesleysimplicio/simplicio (public)

## Changes (from CHANGELOG.md)

- Universal adapter layer: 82 comandos mapeados de Claude Code (22), Codex (17), Hermes (26), OpenClaw (12)
- Pre/post hook engine for automatic token collection in savings ledger
- `redirect_to_simplicio()` — intercepts external agent calls
- 58 new integration tests (total: 228)
- Benchmark: 10,600 tokens saved per task (77%)
- main.rs: 107K → 84K lines (-22,606)
- 23 E0308 errors fixed

## CI Fix Applied

The release.yml on the public distro repo used `jq -r .version` which doesn't exist on `windows-latest` runners. Fixed to `ConvertFrom-Json` via PowerShell:

```yaml
- name: Read version from manifest
  id: ver
  shell: pwsh
  run: echo "version=$((Get-Content simplicio-update-manifest.json | ConvertFrom-Json).version)" >> $env:GITHUB_OUTPUT
```

## Release-Only Actions Policy (implemented this session)

- simplicio-runtime: replaced ALL workflows (10+) with single `release.yml` triggered on `release: [published]`
- All 10 old workflows renamed to `.disabled` (can re-enable by removing suffix)
- Actions disabled on 28 other wesleysimplicio repos via API
- Only `simplicio` (public distro repo) keeps push-triggered `release.yml` (essential for distribution pipeline)

## New GHA Workflow Structure

The `simplicio-runtime/.github/workflows/release.yml` now has 3 sequential steps after build:

1. **Push to distro repo** (requires `GH_PAT_PUBLIC_REPO` secret)
2. **FTP deploy** (requires `FTP_HOST`, `FTP_USER`, `FTP_PASS`, `FTP_PATH` secrets)
3. **PyPI publish** (requires `PYPI_API_TOKEN` secret — binary-only wheels, no source)

All secrets are configured via `gh secret set` on simplicio-runtime.

## External Release Tagging

The public distro repo has its own `v1.2.0` tag (separate from simplicio-runtime's). CI creates this automatically from the manifest. After push, verify with `gh release list -R wesleysimplicio/simplicio` and edit to `--latest --prerelease=false` if needed.

## FTP Deploy

Deploy via `lftp mirror -R` from `simplicio-runtime/site/` to `ftp.simpleti.com.br:/public_html/`.
The Simplicio site lives at `/public_html/simplicio/` (from `site/simplicio/` source).
FTP mode, NOT SFTP. Host cert subjectAltName mismatch — bypass with `set ssl:verify-certificate no`.

## Site Source Locations (2 places)

The site HTML/CSS/JS lives in TWO locations that can diverge:

| Location | Type | Git-tracked | Has dist/ |
|----------|------|-------------|-----------|
| `simplicio-runtime/site/simplicio/` | Submodule inside runtime repo | ✅ Yes (runtime git) | ❌ No (gitignored) |
| `~/Projetos/saas/simplicio-site/` | Standalone working copy | ❌ No | ✅ Yes (old binaries) |

The GHA workflow clones runtime repo fresh, so `dist/` must be provided by the built artifacts.
For manual deploys, use the standalone copy and sync `version.txt` + binaries.

## Verification After Deploy

- `curl -s "https://simpleti.com.br/simplicio/version.txt?$(date +%s)"` → `1.2.0` (cache-buster needed)
- `curl -sI "https://simpleti.com.br/simplicio/dist/simplicio-darwin-arm64"` → 200 OK
- Installed binary: `~/.local/bin/simplicio version` → `simplicio-runtime 1.2.0`
- PyPI: `pip install simplicio-installer` or `curl -s https://pypi.org/pypi/simplicio-installer/1.2.0/json`

## Key Correction From Wesley

**Não buscar no código o que está no CHANGELOG/release notes.** A resposta sobre
"o que essa versão entrega?" está sempre no CHANGELOG.md ou body da GitHub Release,
não no código fonte. Grep no código é o ÚLTIMO recurso, não o primeiro.

## macOS Binary Install (xattr fix)

After copying a newly compiled binary, macOS may SIGKILL (137) it. Fix:
```bash
xattr -d com.apple.provenance ~/.local/bin/simplicio 2>/dev/null || true
codesign --force --sign - ~/.local/bin/simplicio 2>/dev/null || true
```

## Published Channels (v1.2.0)

| Channel | Status | Detail |
|---------|--------|--------|
| GitHub Release (distro repo) | ✅ Latest | v1.2.0 with 4 assets |
| Master branch (distro repo) | ✅ | `049ba0b` — CI fix + release metadata |
| PyPI (simplicio-installer) | ✅ | v1.2.0 |
| Homebrew formula | ✅ | v1.2.0, SHA `d6d6eee7...` |
| npm package.json | ✅ | v1.2.0 bumped (no publish) |
| Website (simpleti.com.br/simplicio/) | ✅ | version.txt=1.2.0, binary in dist/ |

## Windows Binary Note

Cross-compilation for `x86_64-pc-windows-gnu` failed on macOS due to toolchain
issue (Homebrew Rust vs rustup Rust sysroot conflict). The `simplicio.exe` in
the distro repo is still v1.0.4. Fix: build natively on Windows (CI does this
automatically when triggered by push to master).
