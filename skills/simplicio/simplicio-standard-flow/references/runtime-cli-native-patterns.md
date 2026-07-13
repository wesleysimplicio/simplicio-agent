# Runtime CLI Native Patterns (support file)

Concrete, verified patterns for using the Simplicio Runtime CLI as the native
execution path (mandate: "Utilize sempre runtime cli nativo"). Companion to the
`simplicio-standard-flow` SKILL.md.

## 1. Deterministic edit on this host

The Rust `simplicio edit` top-level can fall through to a `compat` wrapper and
return a plan template instead of applying. The binary that actually applies an
edit-plan on the Simplicio host is **`simplicio-py`**:

```bash
# Preview (dry-run) — shows unified diff + edit-result JSON
simplicio-py edit --repo <repo> --plan /tmp/plan.json --dry-run --json

# Apply
simplicio-py edit --repo <repo> --plan /tmp/plan.json --apply --json
```

Edit-plan shape (confirmed working):

```json
{
  "schema": "simplicio.edit-plan/v1",
  "file": "docs/foo.md",
  "expect_sha256": "<sha256 before change>",
  "operations": [
    { "op": "replace", "find": "exact old text", "with": "new text" }
  ]
}
```

- Always set `expect_sha256` to the file's current hash (compute with
  `sha256sum <file>` through `simplicio shell compact`).
- The apply result JSON reports `before_sha256` / `after_sha256` and
  `token_ledger.estimated_paid_tokens_saved` — use it as evidence.
- `mechanical_only: true` confirms 0 LLM tokens were spent.

## 2. `simplicio shell compact` — slice vs spill

`simplicio shell compact -- <cmd>` returns a compressed `slice` and writes the
FULL output to `.simplicio/spill/<timestamp>-<cmd>-<hash>.log`.

- If the slice looks truncated (e.g. `git diff` shows `+0 -0` but `git status`
  lists the file as modified), read the spill file:
  ```bash
  read_file path=/Users/wesleysimplicio/Projetos/ai/<repo>/.simplicio/spill/<name>.log
  ```
- Piping inside the command (`| head`, `| tail`) increases the chance the slice
  is cut — prefer the raw command + spill read, or `git diff` without pipe.
- Never conclude "no changes" from the slice alone.

## 3. Build-churn separation before commit

`cargo build` / `npm install` dirty lockfiles (`Cargo.lock`, `package-lock.json`)
with unrelated entries. Before staging:

```bash
simplicio shell compact -- git status --short
simplicio shell compact -- git diff --stat
# if Cargo.lock / package-lock.json show unrelated churn:
git checkout -- Cargo.lock          # or: git restore Cargo.lock
```

Then stage only the intended files and commit. The runtime pre-commit gate
(`hooks/pre-commit` → `simplicio deliver review`) validates but does NOT filter
lock churn.

## 4. Commit + closure

- On the Simplicio host, `main` is the working branch; `git push -u origin HEAD`
  lands directly on `origin/main` (per the user's "evolucao -> main direto"
  mandate).
- The pre-commit hook runs automatically and prints `[simplicio-gate] ✓` on pass.
- For the runtime's own loop-compliance contract, document closure as a PR to
  `main` with explicit what-changed / how-validated / evidence — but the host
  norm is direct push to `main` (zero-question mandate).

## 5. Anti-contour rule

If a runtime command appears missing/broken:
1. Probe the canonical subcommand (e.g. `simplicio file read` not `simplicio read`).
2. If genuinely absent/broken, FIX the runtime via `simplicio-py edit --plan`
   (dispatch fix in `src/commands/mod.rs`), rebuild, test, push.
3. Only after (1)+(2) exhausted is a verified native fallback acceptable — and
   it must be logged as a runtime gap to evolve.
