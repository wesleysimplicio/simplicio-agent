# Release v0.9.4 — Session Reference (2026-06-12)

## Context

87 commits since v0.9.3. Massive merges from PRs #982, #1012, #1027, #1028.
17 compilation errors introduced by PR #1012 merge.

## Compilation Fixes

17 errors across 7 files. Fixed by a single delegate_task subagent:

| File | Error | Fix |
|------|-------|-----|
| `behavior_command.rs` | Broken string escapes (`""consent`) | `"\"consent"` |
| `autonomia_engine.rs` | `format!(r#"..."+"\n")` concat | Single format string |
| `skills_v2.rs` | `f32 * f64` mismatch | `as f64` |
| `git_integrations.rs` | Unused variable | `_file` |
| `skill_health.rs` | `join("",""""")` syntax | `join("\",\"")` |
| `infra_advanced.rs` | `starts_with(&&String)` | `.as_str()` |
| `memory_rerank.rs` | Lifetime mismatch | `'a` lifetime param |
| `main.rs` | Module as function + arg types | Proper dispatch |

## Release Steps (Manual)

```bash
# 1. Verify consistency
grep ^version Cargo.toml | sed 's/version = "\(.*\)"/\1/'
cat site/simplicio/version.txt

# 2. Build
cargo build --release --locked

# 3. Update site submodule
echo "0.9.4" > site/simplicio/version.txt
cp target/release/simplicio site/simplicio/dist/simplicio-darwin-arm64
cd site && git add -A && git commit -m "feat(simplicio): update binary to v0.9.4"
git push origin master
cd .. && git add site && git commit -m "chore: update site submodule"
git push origin main

# 4. Tag + GitHub Release
git tag -a v0.9.4 -m "v0.9.4 — infraestrutura avançada + autonomia"
git push origin v0.9.4
gh release create v0.9.4 --repo wesleysimplicio/simplicio-runtime \
  --title "v0.9.4" --notes "..." --clobber
gh release upload v0.9.4 target/release/simplicio \
  --repo wesleysimplicio/simplicio-runtime

# 5. FTP deploy (needs .ftp-credentials in site/deploy/)
cd site && ./deploy/deploy-ftp.sh
```

## Cross-Session Coordination

- `prs_batch.rs` was created by a parallel Hermes session. This session initially deleted it (stale cleanup), breaking the build.
- Fix: restore `mod prs_batch;` + dispatch line in `main.rs`, commit the file, and **send a message to #hermes**.
- Rule: always message `#hermes` about structural changes (new modules, mod declarations, file deletions).

## Verification

```bash
# Version consistency
grep ^version Cargo.toml          # 0.9.4
cat site/simplicio/version.txt     # 0.9.4
git describe --tags --exact-match HEAD  # v0.9.4

# Release URL
open https://github.com/wesleysimplicio/simplicio-runtime/releases/tag/v0.9.4
```
