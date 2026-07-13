---
name: neural-memory-seeding
description: Persist durable operator/project learnings — and absorb external/third-party repository knowledge — into the Simplicio neural database bootstrap and forward migrations, then validate, commit, and push safely. Covers the exact `simplicio edit` mechanical-plan schema for writing files in managed repos and the real seeding pipeline (knowledge_ingestor → seeds.sql → memory init).
---

# Neural Memory Seeding

## When to use
- The user says the important new knowledge is already "in memory" and wants it persisted into the repo.
- You need new clones / fresh databases to inherit durable facts.
- You are promoting stable operator preferences, workflow contracts, or project doctrine into the neural DB bootstrap.

## Do not use for
- Temporary session state
- Resolved transient errors
- Artifact logs, PR numbers, or other stale operational breadcrumbs
- Environment-specific breakage

## Core rule
Distill memory into a **small set of durable facts**, then persist them in **both** places:
1. `.simplicio/memory/seeds.sql` for bootstrap seeding
2. `migrations/000X_<topic>.sql` for forward application on existing DBs

Do not dump raw conversation text. Convert it into stable, reusable facts.

## Steps
1. **Orient first**
   - Locate `.simplicio/memory/seeds.sql`
   - Locate existing `migrations/000*.sql`
   - Confirm the latest migration number before adding a new one

2. **Distill what is actually durable**
   Good candidates:
   - user execution preferences that govern future work
   - project doctrine / operating principles
   - stable workflow contracts
   - anti-duplication / evidence / validation rules

   Bad candidates:
   - branch names
   - one-off bugs fixed today
   - timing / timeout incidents
   - unresolved scratch files or temporary repo state

3. **Encode as facts with stable IDs**
   Preferred shape:
   - `stable_id`: deterministic and scoped, e.g. `fact:simplicio-runtime:<topic>-v1`
   - `kind`: `fact`
   - `source`: `seed://...` in seeds, `migration://000X_...` in migration
   - concise `title`
   - compact `content`
   - useful `tags`
   - elevated `weight` only for truly central doctrine

4. **Write the seed block**
   - Append new `INSERT OR IGNORE INTO memory_items(...) VALUES(...)` entries near the end of `.simplicio/memory/seeds.sql`
   - Keep the file idempotent
   - Preserve the final `COMMIT;`

5. **Write the forward migration**
   - Create `migrations/000X_<topic>.sql`
   - Reinsert the same durable facts using `INSERT OR IGNORE`
   - End with `INSERT OR IGNORE INTO schema_migrations(id) VALUES ('000X_<topic>');`

6. **Validate with sqlite smoke**
   - Run a scratch `sqlite3 :memory:` load of schema + new migration
   - Verify two things explicitly:
     - the migration ID is present in `schema_migrations`
     - the newly added `stable_id`s are queryable from `memory_items`

7. **Interpret schema noise correctly**
   If the bootstrap schema includes compatibility `ALTER TABLE` lines, a scratch replay can emit duplicate-column parse errors such as `duplicate column name: metadata` / `provenance`.
   Treat that as **non-blocking** if:
   - the migration row was inserted
   - the new facts were inserted and queryable

8. **Commit narrowly**
   - Stage only the intended seed and migration files unless the user explicitly asked for more
   - Commit with a narrow message describing the memory persistence action
   - Push the active branch

9. **Report honestly**
   Include:
   - which facts were persisted
   - migration filename
   - commit SHA
   - push target
   - any remaining untracked files not included

## Pitfalls
- Do not persist raw chat dumps into seeds.
- Do not create a migration without updating seeds; fresh bootstrap and forward migration must stay aligned.
- Do not treat compatibility `ALTER TABLE` duplicate-column noise as a failure if the actual seed facts validated.
- Do not overfit the memory to today's branch / bug / PR.
- **Two `seeds.sql` locations.** The tracked artifact is
  `<repo>/.simplicio/memory/seeds.sql` (committed, applied by `simplicio memory init`
  on fresh clones). The LIVE neural DB reads `~/.simplicio/memory/seeds.sql`
  (home). If you only update the home copy, the commit is empty and a fresh
  clone loses the facts. Always append to the REPO copy; apply the migration to
  the live DB with `sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite < migration.sql`.
- **`simplicio memory ingest` is not a general write path.** It expects to run
  from the `simplicio-runtime` checkout (it shells out to
  `scripts/ingest_project.py` relative to cwd) and fails with
  `ingest orchestrator not found` elsewhere. The real pipeline for absorbing an
  external repo is: `scripts/ingestors/knowledge_ingestor.py --repo <ext> --output <jsonl>`
  → `build_seed_sql.py` → `seeds.sql` → `simplicio memory init`. For curated
  facts, write the `INSERT OR IGNORE` rows by hand (see column schema below).
- **SQLite schema replay noise.** Replaying `memory-schema.sql` in a scratch
  `:memory:` db throws `duplicate column name: metadata` from compatibility
  `ALTER TABLE` lines. Tolerate it (the column already exists) — validate by
  applying the migration to the LIVE db and `SELECT`ing the new `stable_id`s.
- **`memory_items` column order.** Inserts must list
  `(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight)`
  — `metadata`/`provenance` columns exist but are auto-filled; do not include
  them in hand-written inserts.

## Skill-catalog indexing — stable identity and full-procedure loading

When persisting an index of many installed skills, never use only the display name as
`stable_id`: categories can contain homonymous skills and `INSERT OR IGNORE` would silently
drop entries. Derive the ID from the canonical relative `SKILL.md` path (for example,
`skill:index:path:<sha256(path)[:24]>`) and verify the inserted row count equals the discovered
path count. Store the searchable name/description/path in neural memory; keep the complete
procedure in the on-disk `SKILL.md` and load it on demand. This preserves retrieval coverage
without duplicating hundreds of skill bodies into SQLite.

## Shared-plan path pitfall

A plan created inside `simplicio shell` may live in that command's isolated spill/scratch
context and be invisible to a subsequent native `simplicio edit` process. When a plan must be
consumed by the CLI, create it through the host file writer or native shell in a shared path,
then invoke `simplicio edit --plan` from the target repository. If the CLI reports `plan file not
found`, retry by regenerating the plan in a shared host-visible path; do not fall back to manual
repository edits. Validate the plan and target repository after the retry.

## Writing files in a managed repo — `simplicio edit` plan schema

The `simplicio-agent` plugin BLOCKS native `write_file`/`patch` inside
`simplicio-runtime` (and other managed repos). All writes go through
`simplicio edit --plan <json> --repo <repo>`. The plan schema is strict and
undocumented outside the binary; the format that actually works is:

```json
{
  "file": "<repo-relative-path>",
  "operations": [
    { "op": "create", "text": "<full file content>" },
    { "op": "replace", "find": "<exact old text>", "with": "<new text>" },
    { "op": "append", "text": "<text to append>" }
  ]
}
```

- Plan is an OBJECT with a `file` key + `operations` array — NOT a bare array.
- Each operation needs `op`. Supported ops: `replace`, `replace_all`,
  `insert_before`, `insert_after`, `replace_line`, `insert_at_line`,
  `delete_line`, `append`, `prepend`, `create`, `apply_block`.
- `create` (new file) uses the field `text`, NOT `content`. `replace` uses
  `find`/`with` (exact match). `append`/`prepend` use `text`.
- Common failures seen in practice (each maps to a missing field):
  - `edit plan must contain an "operations" array` → you passed a bare array.
  - `edit plan must specify a target "file"` → missing the top-level `file` key.
  - `unknown op "write"` → op is `create`, not `write`.
  - `missing required string field "text"` on create → use `text`, not `content`.
- `simplicio edit` reports a token ledger (paid vs saved vs an LLM edit); it is
  the canonical deterministic write path — prefer it over hand-editing. See
  `references/simplicio-edit-mechanical-plan.md` for the full op list + worked
  example (ADR creation that failed 4× then succeeded).

## Output checklist
- seed updated
- migration created
- sqlite smoke verified
- commit created
- push completed
- leftover untracked files disclosed

## References
- See `references/sqlite-smoke-validation.md` for the exact validation pattern and interpretation of duplicate-column compatibility noise.
