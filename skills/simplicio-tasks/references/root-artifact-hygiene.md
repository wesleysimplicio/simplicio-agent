# Root artifact hygiene for issue-drain runs

Session-derived notes for cleaning repo-root session artifacts without damaging tracked state.

## Verified pattern
- A cleanup pass removed repo-root artifacts such as `savings_*.json`, `status_snapshot.json`, `validation_chat.json`, `duplicate_fn_report.txt`, `orphans_final.txt`, `test_escape.rs`, and `remove_wavespeed.py`.
- `.gitignore` should explicitly cover:
  - `savings_*.json`
  - `*_debug.json`
  - `status_snapshot.json`
  - `validation_chat.json`
  - `duplicate_fn_report.txt`
  - `orphans_*.txt`
  - `test_escape.rs`
  - `remove_wavespeed.py`
  - `.simplicio/decision-cache/`
  - `.simplicio/handoff/`
- Verify ignore coverage with `git check-ignore -v <paths...>` before declaring the root clean.

## Pitfall
- Do not blindly `rm -rf` directories under `.simplicio/` during cache cleanup. Some files in that tree can be tracked; if a tracked cache file disappears, restore it from git before finishing.

## Verification checklist
- `git status --short` should only show expected source changes.
- `git check-ignore -v` should explain each root artifact path.
- If a cleanup touched generated outputs, rerun the relevant build/test gate after the delete/ignore change.

## Session notes (2026-07-07)
- Before deleting root artifacts, inspect `git status --short --branch` and `git diff --cached --name-only --diff-filter=D` so staged deletes are not mistaken for fresh untracked noise.
- When the root includes both tracked and untracked cleanup candidates, prefer `git check-ignore -v <paths...>` plus a references grep over blind `rm`; then remove only the confirmed artifact set.
- In this repo, a cleanup pass can surface an unrelated existing build failure in `src/main_parts/chunk_06.rs` (`GuardianRole` out of scope). Do not attribute that to root-artifact cleanup; keep the verification report honest and separate.
- If `git status` shows a workflow pair like `.github/workflows/ci.yml.disabled` deleted plus `.github/workflows/ci.yml` untracked, inspect it as a rename/restoration artifact before touching CI files.
