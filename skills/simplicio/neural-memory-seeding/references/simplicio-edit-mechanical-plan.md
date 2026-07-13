# `simplicio edit` mechanical-edit plan schema (reference)

Discovered the hard way while writing `docs/ADR-2026-07-12-ORCA-ABSORPTION.md`
into the managed `simplicio-runtime` repo (native `write_file` was blocked by
the Simplicio plugin). The plan JSON is stricter than the docs imply.

## Canonical working plan

```json
{
  "file": "docs/ADR-2026-07-12-ORCA-ABSORPTION.md",
  "operations": [
    { "op": "create", "text": "<entire file content>" }
  ]
}
```

Run: `simplicio edit --plan /tmp/plan.json --repo /Users/wesleysimplicio/Projetos/ai/simplicio-runtime`

## Failure → fix map (real transcript)

| Error | Cause | Fix |
|---|---|---|
| `edit plan must contain an "operations" array` | Plan was a bare JSON array `[{...}]` | Wrap: `{"file":"...","operations":[...]}` |
| `edit plan must specify a target "file"` | Missing top-level `file` key | Add `"file": "<repo-relative-path>"` |
| `operation 0: unknown op "write"` | Used `op:"write"` | Use `op:"create"` for new files |
| `operation 0 is missing required string field "text"` | `create` used `content` | Rename field to `text` |

## Supported ops (from runtime validation)

`replace` (needs `find`+`with`), `replace_all`, `insert_before`, `insert_after`,
`replace_line`, `insert_at_line`, `delete_line`, `append` (field `text`),
`prepend` (field `text`), `create` (field `text`), `apply_block`.

- `replace`: `find` must be EXACT substring; `with` is the replacement.
- `create`: creates a new file; field is `text` (NOT `content`).
- `append`/`prepend`: add to existing file; field is `text`.

## Token ledger output (expected)

```
  1. create  -- 3831 char(s)
  created new file
  sha256: ... -> ...
  token ledger: 0 paid tokens spent, ~988 paid tokens saved vs an LLM edit
```

Zero paid tokens = deterministic write succeeded. If you see a paid-token cost,
the plan fell back to LLM editing — check the schema.
