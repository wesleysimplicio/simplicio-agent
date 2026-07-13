# SQLite smoke validation for neural-memory seeding

Use this when adding facts to `.simplicio/memory/seeds.sql` and a new `migrations/000X_*.sql`.

## Goal
Prove that the forward migration is effective without needing a live production DB.

## Pattern
1. Concatenate the bootstrap schema and the new migration into a temporary SQL script.
2. Load it into `sqlite3 :memory:`.
3. Query:
   - `schema_migrations` for the new migration ID
   - `memory_items` for the newly added `stable_id`s

## Success criteria
The smoke is good when both are true:
- the migration ID appears in `schema_migrations`
- the new durable facts are present in `memory_items`

## Important nuance
The bootstrap schema may contain compatibility `ALTER TABLE` statements such as:
- `ALTER TABLE memory_items ADD COLUMN metadata TEXT;`
- `ALTER TABLE memory_items ADD COLUMN provenance TEXT;`

When replayed against a fresh in-memory DB, sqlite can emit parse errors like:
- `duplicate column name: metadata`
- `duplicate column name: provenance`

If the migration row and seeded facts still appear in query output, treat those duplicate-column messages as compatibility noise, not as a blocker.

## Reporting guidance
Report three things explicitly:
- migration id observed
- fact stable_ids observed
- whether duplicate-column noise appeared and why it was considered non-blocking
