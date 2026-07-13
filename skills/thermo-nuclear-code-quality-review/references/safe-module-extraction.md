# Safe Module Extraction from Giant Files

Use when remediating findings from a codebase-wide audit — extracting inline functions/modules from a 10K+ line file into separate .rs files.

## Prerequisites

- The file compiles cleanly before you start
- You understand the module structure (Rust `mod` + `use super::*` semantics)
- You have `cargo check` available to verify each extraction

## Core Principle: Extract Modules, Not Functions

**Do NOT extract a single function in isolation** unless it has zero dependencies on other inline code. Instead:

- **Extract inline `mod { }` blocks** (easiest, safest) — the module already has a boundary
- **Extract test modules** (`#[cfg(test)] mod tests { }`) — they use `use super::*` and are naturally isolated
- **Extract groups of related functions** — if 5 utility functions all reference the same types, move them together

## Safe Extraction Steps

### 1. Extract inline `mod NAME { }`
```bash
# Find the module boundaries (brace matching)
sed -n 'START_LINE,END_LINEp' main.rs > new_module.rs
# Replace inline block with file-based mod
sed -i.bak 'START_LINE,END_LINEc\
mod NAME;' main.rs
# Verify
cargo check
```

### 2. Extract `#[cfg(test)] mod tests { }`
```bash
# Extract everything INSIDE the braces (line after `mod tests {` through the closing `}`)
sed -n 'MOD_START+2,MOD_END-1p' main.rs > main_tests.rs
# Replace the full block (including #[cfg(test)]) with file reference
sed -i.bak 'MOD_START_LINE,MOD_END_LINEc\
#[cfg(test)]\
mod main_tests;' main.rs
# The extracted file uses `use super::*;` which still refers to the crate root
# Verify
cargo check
```

### 3. Extract a top-level function
More complex because of dependencies. Strategy:

**A. If the function references types/functions from the crate root:**
```rust
// In new file: use_module.rs
use crate::DependencyType;
pub fn my_function(args) -> Result<(), String> { ... }
```

**B. In main.rs:**
```rust
mod use_module;
// Replace inline function body with:
use_module::my_function(args)
```

**C. Update callers:**
If other modules called `crate::my_function(...)`, update to `crate::use_module::my_function(...)` or re-export at crate root:
```rust
pub use use_module::my_function;
```

### 5. Alternative: #[path = "..."] for test modules

When the extracted module references items via `use super::*` and you want to keep the module at a different filesystem path than its `mod` name:

```rust
// In main.rs:
#[path = "main_tests.rs"]
mod tests;
```

This keeps `mod tests` (not `mod main_tests`) so all existing `use super::*;` references and `crate::tests::` callers work without updating any import paths. Useful when extracting a giant `mod tests { }` block where renaming the module would require touching hundreds of test references.

### 6. Flat file to directory module conversion

When a single `.rs` file grows so large it needs sub-modules:

```bash
# Convert flat file to directory module:
mv src/big_module.rs src/big_module/
# Rename to mod.rs
mv src/big_module/big_module.rs src/big_module/mod.rs  # wrong!
# CORRECT:
mkdir src/big_module/
mv src/big_module.rs src/big_module/mod.rs
# Now create sub-modules:
touch src/big_module/part_a.rs
touch src/big_module/part_b.rs
```

In `src/big_module/mod.rs`, declare sub-modules:
```rust
pub mod part_a;
pub mod part_b;
```

Callers still use `crate::big_module::*` — the path doesn't change. See `rust-monorepo-refactoring` for detailed post-extraction visibility fixes.

### 7. Post-extraction test visibility failures

After extracting types to a sub-module, tests in main.rs lose access to private items:

```rust
error[E0603]: constant `X` is private
```

Fix: Make the item `pub(crate)` in the sub-module, or add a `pub(crate) use` re-export in main.rs after the `mod` declaration:
The `dispatch` function (1,400+ lines) is a giant match statement routing command → handler. To extract it:

```rust
// In dispatch.rs
pub fn dispatch(command: &str, args: Vec<String>) -> Result<(), String> {
    // ... giant match
    // Reference handler functions via crate:: or pass as closures
}
```

## Verification Checklist (after EACH extraction)

1. ✅ `cargo check` passes (zero errors)
2. ✅ No behavioral change — tests still pass (`cargo test`)
3. ✅ The extracted file has a meaningful name
4. ✅ `#![allow(dead_code)]` was NOT added (the extraction should wire things properly)
5. ✅ No duplicate symbol errors (the old inline code was fully removed)

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Missing `use` imports | "cannot find type X" | Add `use crate::X;` or `use super::X;` |
| `pub(crate)` visibility | "function X is private" | Make the function `pub(crate)` or `pub` |
| Circular module deps | "circular dependency" | Extract shared types to a separate module first |
| Brace mismatch | extraction includes wrong lines | Count braces carefully; use `rustfmt` on the extracted file |
| `use super::*` in extracted file | "unresolved import" | Change to `use crate::*` if super doesn't resolve correctly |
| **Parallel extraction conflict** — two agents extract different blocks from same file at same time | Patches fail because line numbers shifted, or mod declarations get duplicated | 1) Structure tasks so each agent owns different files. 2) If they must share a file, dispatch in waves not parallel. 3) Always run `cargo check` at the END after all agents finish — never trust individual verifications. |

## Why `use super::*` Works After Extraction

In Rust, `mod foo;` in `main.rs` creates `foo` as a child of the crate root. `super` inside `foo` refers to the parent — which IS the crate root (main.rs). So `use super::*` in an extracted file works EXACTLY like `use super::*` inside an inline `mod { }` block.
