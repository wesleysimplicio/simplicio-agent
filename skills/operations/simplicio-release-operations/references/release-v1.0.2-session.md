# Release v1.0.2 — GHA Partial Failure Recovery

**Date:** 2026-06-17
**Context:** GHA Release workflow ran but only produced a Windows binary.
macOS ARM64 and Linux x86_64 binaries were built locally and uploaded manually.

## Initial state

- Version `1.0.2` already tagged and released on GitHub
- Only asset: `simplicio-windows-x64` (18MB) in both repos
- Site at simpleti.com.br still on v1.0.0
- Local binaries ready: `target/release/simplicio` (macOS ARM64, 18MB) and
  `target/x86_64-unknown-linux-gnu/release/simplicio` (Linux x86_64, 18MB, built
  without `in-process-llm` via zigbuild)
- GHA Release runs were failing (conclusion=failure), root cause not investigated
  (likely billing or runner issue)

## Commands used

### Check existing release assets
```bash
gh release view v1.0.2 --repo wesleysimplicio/simplicio-runtime --json assets
gh release view v1.0.2 --repo wesleysimplicio/simplicio --json assets
```

### Upload macOS ARM64 to private repo
```bash
cp target/release/simplicio /tmp/simplicio-darwin-arm64
gh release upload v1.0.2 /tmp/simplicio-darwin-arm64 \
  --repo wesleysimplicio/simplicio-runtime --clobber
```

### Upload Linux x86_64 to private repo
```bash
cp target/x86_64-unknown-linux-gnu/release/simplicio /tmp/simplicio-linux-x64
gh release upload v1.0.2 /tmp/simplicio-linux-x64 \
  --repo wesleysimplicio/simplicio-runtime --clobber
```

### Repeat for public dist repo
```bash
gh release upload v1.0.2 /tmp/simplicio-darwin-arm64 \
  --repo wesleysimplicio/simplicio --clobber
gh release upload v1.0.2 /tmp/simplicio-linux-x64 \
  --repo wesleysimplicio/simplicio --clobber
```

### Clean up incorrectly-named asset (first upload used bare filename "simplicio")
```bash
gh release delete-asset v1.0.2 simplicio \
  --repo wesleysimplicio/simplicio-runtime --yes
```

### Prepare publish directory + SHA256SUMS
```bash
mkdir -p publish/simpleti/simplicio/dist
cp target/release/simplicio publish/simpleti/simplicio/dist/simplicio-darwin-arm64
cp target/x86_64-unknown-linux-gnu/release/simplicio \
   publish/simpleti/simplicio/dist/simplicio-linux-x64
cd publish/simpleti/simplicio/dist
rm -f SHA256SUMS
for f in simplicio-*; do [[ -f "$f" ]] || continue; shasum -a 256 "$f" >> SHA256SUMS; done
```

### Update site version.txt
```bash
echo "1.0.2" > site/simplicio/version.txt
```

### Discord notification
```bash
send_message(target="discord:#simplicio-runtime", message="✅ Release v1.0.2 completa! ...")
```

## Final state

Both repos have 3 assets:
- `simplicio-darwin-arm64` (18.7MB)
- `simplicio-linux-x64` (18.4MB)
- `simplicio-windows-x64` (18.1MB)

## Blockers

- **FTP deploy**: `deploy/.ftp-credentials` missing in simplicio-runtime repo.
  Site still on v1.0.0 at simpleti.com.br. Cannot deploy without credentials.
- **GHA pipeline**: Still failing. Not investigated — local upload sufficed.

## Links

- https://github.com/wesleysimplicio/simplicio-runtime/releases/tag/v1.0.2
- https://github.com/wesleysimplicio/simplicio/releases/tag/v1.0.2
