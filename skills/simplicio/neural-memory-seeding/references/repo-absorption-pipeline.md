# External repo absorption → neural seed + ADR

Condensed from the 2026-07-12 `stablyai/orca` absorption. Use this when the user asks to "analyze a repo and absorb all its commands into memory, plus a seed and an ADR".

## Pipeline
1. **Clone shallow** (186MB/8159 files is fine): `git clone --depth 1 <url> ~/Projetos/ai/<name>`.
2. **Orient without `runtime map --repo`** — see drift gap below. Instead use `find`/read_file on the repo's own structure.
3. **Extract the command surface from source, not docs.** For Orca, the CLI was declaratively defined in `src/cli/specs/*.ts` (`COMMAND_SPECS` with 15 groups). Grepped `path: [...]` arrays → **184 commands**. Docs overstate or understate; source is ground truth.
4. **Curate, don't dump.** Write 5–8 *durable facts* (overview, CLI-surface-summary, architecture-model, orchestration-layer, integration-points) as JSONL `simplicio.memory-seed-row/v1`. Never paste raw file trees.
5. **Seed into the REPO** `seeds.sql` + a forward `migrations/000X_<topic>.sql` (idempotent `INSERT OR IGNORE`). Apply the migration to the **live** DB: `sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite < migration.sql`.
6. **Write an ADR** (`docs/ADR-YYYY-MM-DD-<TOPIC>.md`) recording: context, decision, the 2–3 runtime gaps discovered, integration points. Create via `simplicio edit --plan` (`op: create`, field `text`) — native write_file is blocked in managed repos.
7. **Validate + commit narrow + push.** `sqlite3` direct query to confirm `count(*)` of new `stable_id`s; `git add` only the 3 files; push.

## JSONL fact schema (verified)
```json
{"schema":"simplicio.memory-seed-row/v1","stable_id":"project:orca:overview-v1","kind":"project_doc","source":"seed://orca/overview","title":"...","content":"...","artifact_path":"...","source_hash":"...","tags":"orca,ai-orchestrator","weight":5}
```
`source_hash` = `sha256(content)`. `stable_id` deterministic and scoped.

## Gap discovered: `runtime map --repo` drift
`simplicio runtime map --repo /tmp --for-llm markdown` **ignored `--repo`** and emitted the *own* Simplicio Runtime map (canonical command `simplicio`, 66+ commands). The map command only orients the runtime's own repo. **For third-party repos, orient with `find` + `read_file` directly** — do not rely on `runtime map --repo <external>`. Log as a runtime evolution gap (file an issue).

## Verification that "I know it now"
After seeding, prove recall: `simplicio memory "orca AI orchestrator worktrees"` → retrieval result with the seeded `project_doc`. A `no_results` on a quoted sub-phrase is normal (FTS indexes content words); retry with terms that exist in the fact text.
