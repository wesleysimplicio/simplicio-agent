# edit-plan schema quickref (simplicio edit --plan)

Authoritative source: `simplicio-runtime/schemas/edit-plan.schema.json`.
Minimal plan that applies (field `schema` is OPTIONAL):

```json
{
  "file": "caminho/relativo/ao/repo",
  "operations": [
    { "op": "replace", "find": "texto exato ancorado", "with": "substituição" }
  ]
}
```

Apply:
```bash
simplicio edit --plan /tmp/plan.json --json
# ou preview:
simplicio-py edit --repo <repo> --plan /tmp/plan.json --dry-run --json
```

## `op` enum and required payload fields
| op | required fields | notes |
|----|----------------|-------|
| `replace` | `find`, `with` | 1 occurrence by default; `count` raises max |
| `replace_all` | `find`, `with` | all occurrences |
| `insert_before` | `find`, `text` | insert `text` before `find` |
| `insert_after` | `find`, `text` | insert `text` after `find` |
| `replace_line` | `line`, `text` | 1-indexed line replacement |
| `insert_at_line` | `line`, `text` | insert at 1-indexed line |
| `delete_line` | `line` | delete 1-indexed line |
| `append` | `text` | append to end of file |
| `prepend` | `text` | prepend to start of file |
| `create` | `text` | create new file with `text` |

Top-level optional: `expect_sha256` (precondition — edit aborts if file bytes mismatch).

## Failure modes seen in practice (and fixes)
1. `failed to read edit plan <inline>: No such file or directory`
   → `--plan` wants a FILE PATH, not inline JSON. Write the plan to a file first.
2. `edit plan must contain an "operations" array`
   → top-level key is `operations`, not a bare array and not `edits`.
3. `operation 0 is missing string field "op"`
   → each operation needs `"op": "replace"` (etc.) plus its payload fields.
4. `must specify a target "file" (or pass --file)`
   → `file` must be a top-level key (peer of `operations`), not nested inside an operation.

## Gotcha: product vs runtime binary name
`simplicio-agent`'s `scripts/install.sh` historically set `BINARY_NAME="simplicio"`,
which would overwrite the standalone Simplicio Runtime binary on PATH. The product
must install as `simplicio-agent`. If you edit install scripts, keep the product
name distinct from the runtime name.
