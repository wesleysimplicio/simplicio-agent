# Runtime gap fix — top-level `simplicio read` alias (2026-07-09)

Reproduction recipe for when a runtime subcommand "doesn't work" and the fix is
to evolve the runtime's dispatch rather than fall back to native host tools.

## Symptom
```
$ simplicio read --repo . hooks/pre-commit
objective : read
repo      : .
intent    : query
risk      : safe
status    : pending
acceptance_criteria:
  (none)
```
The top-level `simplicio read` returned a **plan template** (the edit-plan
fallback), not the file contents. Agent treated it as "runtime can't read
files" and reached for native `read_file`. Wrong.

## Root cause
`src/commands/mod.rs` had no `"read"` arm in the top-level match. The token
fell through to the `simplicio edit` path (which accepts a plan JSON string),
so `read` was parsed as an edit-plan spec.

The real read command is `simplicio file read --repo . <path>`:
- `src/commands/mod.rs:661` → `"file" | "files" => crate::file_tools::file_command(args)`
- `src/file_tools.rs:116` → `"read" => file_read(rest)`
- `src/file_tools.rs:172` → `fn file_read(args: Vec<String>)`

## Fix (evolve the runtime, deterministic)
Plan `edit-plan/v1`:
```json
{
  "schema": "simplicio.edit-plan/v1",
  "file": "src/commands/mod.rs",
  "operations": [
    {
      "op": "replace",
      "find": "        // #file: read/write/search\n        \"file\" | \"files\" => crate::file_tools::file_command(args),",
      "with": "        // #file: read/write/search\n        \"file\" | \"files\" => crate::file_tools::file_command(args),\n        // top-level `simplicio read <path>` alias -> file read (was falling\n        // through to the edit-plan fallback). See #2990.\n        \"read\" => crate::file_tools::file_command({\n            let mut a = vec![\"read\".to_string()];\n            a.extend(args);\n            a\n        }),"
    }
  ]
}
```
Apply:
```bash
simplicio edit --plan /tmp/plan_read_alias.json --repo . --dry-run --json   # verify
simplicio edit --plan /tmp/plan_read_alias.json --repo . --commit "fix(cli): top-level 'simplicio read' aliases to file read #2990" --json
cargo build --release
simplicio read --repo . hooks/pre-commit | grep -c "MANDATORY Simplicio gate"   # expect 1
git push origin main
```
Edit plan schema reminder (learned the hard way, 3 iterations):
`op: replace` needs **`find`** + **`with`** (not `old`/`new`). Missing `find`
→ "missing required string field find"; missing `with` → "missing required
string field with".

## Measured outcome
- `edit --plan` result: `mechanical_only: true`, `remote_used: false`,
  `estimated_paid_tokens_saved: 38096`.
- Commit `a055c1a9` pushed to `main` (`20d0101f..a055c1a9`).
- After rebuild, `simplicio read --repo . hooks/pre-commit` returns real file
  content (grep count 1 on the MANDATORY gate header).

## Hook context (already strong — agent must honor it)
- `hooks/pre-commit` runs `simplicio deliver review --base HEAD --json` on every
  commit by any LLM/tool.
- Enable once per clone: `git config core.hooksPath hooks`.
- `.claude/hooks/orient-gate.sh` (matcher `Read|Grep|Glob`) blocks native
  read-only exploration and raw shell verbs `grep/rg/cat/find/sed/awk` unless
  `simplicio` is used; stamps the session when `simplicio` runs.
- Override one commit: `SIMPLICIO_GATE_SKIP=1`; disable gate: `SIMPLICIO_ORIENT_GATE=0`.
