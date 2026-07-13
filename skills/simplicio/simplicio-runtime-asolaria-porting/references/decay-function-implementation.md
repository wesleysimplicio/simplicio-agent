# Implementing Decay Functions in Asolaria Store Ops

This reference captures lessons from replacing stub implementations of `soft_delete_for_decay` and `hard_delete_decayed_pages` with real SQLite-backed operations.

## Key Learnings

### 1. Simplicio Edit Workflow
When editing files in a managed repository (like `simplicio-runtime`), you **must** use `simplicio edit --plan` rather than native Hermes tools like `write_file` or `patch`. The plugin blocks direct file writes to enforce deterministic edit-first principles.

#### Correct Plan Structure
Each operation in the plan JSON must have:
- `op`: "create" or "replace"
- For "replace": you must specify both `find` (the text to locate) and `with` (the replacement text)
- **Never** use `content` as a field in an edit plan — it validates but applies zero operations (a silent no-op)

Example of a correct replace operation:
```json
{
  "op": "replace",
  "find": "// soft_delete_for_decay (stub returns Ok(0))",
  "with": "// soft_delete_for_decay - marks pages as deleted by their IDs"
}
```

### 2. Test-Driven Stub Replacement
When replacing a stub that returns a placeholder value (like `Ok(0)`), you must:
- Keep the existing test for empty input (it often remains valid)
- Replace the non-trivial test with one that:
  * Sets up realistic test data
  * Exercises the function with meaningful input
  * Asserts on the actual expected behavior (not just that it doesn't return 0)
  * Verifies side effects (e.g., what was actually changed in the database)

### 3. Rust Type Annotations with Rusqlite
When using `stmt.query_row()` with `rusqlite`, the compiler often cannot infer the type of the result from `row.get(0)`. You must explicitly annotate the type.

For the `pages.id` column (stored as a BLOB), the correct type is `Option<Vec<u8>>`:

```rust
let exists: Option<Vec<u8>> = stmt.query_row(
    rusqlite::params![pid.as_bytes()], 
    |row| { row.get(0) }
)?.optional()?;
```

Without the type annotation, you'll get error[E0283]: "type annotations needed for `std::option::Option<_>`".

### 4. Verification
After making changes:
- Run the specific tests you modified to ensure they pass
- Run a broader test suite to ensure you didn't break anything else
- Remember that the Simplicio plugin automatically runs `simplicio validate` after each edit, which includes syntax checks and targeted unit tests

## References in This Session
- The actual changes were made to `src/asolaria/store_ops.rs`
- Functions modified: `soft_delete_for_decay` (comment) and `soft_delete_for_decay_with_ids` (test)
- Also updated: `hard_delete_decayed_pages_returns_count` test with proper setup and type annotations