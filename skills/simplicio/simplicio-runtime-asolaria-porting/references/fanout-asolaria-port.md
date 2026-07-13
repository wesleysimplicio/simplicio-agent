# Fan-out Asolaria Port — Recipe (2026-07-09 sprint)

## Clone list (depth-1, JesseBrown1980)
```
asolaria-hbi-hbp          # HBI/HBP codec — verify_chain, ReceiptChain (ALREADY wired in src/asolaria)
asolaria-federation-1024  # council-serve, hookwall, recall lanes
asolaria-asi-os           # fabric node (Rust, 0 crates)
asolaria-os               # microkernel UEFI no_std (high value, complex)
ai-memory                 # long-term memory; core mirrors src/asolaria types
asolaria-agent-memory     # hot-path HBI/HBP .hbp/.hbi
N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED  # N-Nest self-reflective agents
HRM                       # hierarchical memory/reflection
HYPER-BECHS--the-third-set  # BEHCS search set
shannon                  # information theory / encoding
```
Note: `asolaria-nest-prime` does NOT exist (404); the nest lives in the
`N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED` repo.

## What is ALREADY wired (do NOT re-port)
- `src/asolaria/mod.rs` re-exports `asolaria_hbi_hbp::{verify_chain, ReceiptChain, GENESIS}`.
- `sealed_receipt.rs` imports + uses them directly.
- `ai-memory-core` types (`Observation`, `ObservationKind`, `Handoff`, `ids`) are
  mirrored in `src/asolaria/{observation,handoff,ids}.rs`.
- `nest_prime.rs`, `consolidator.rs`, `fedenv.rs`, `hookwall.rs`, `agent_state.rs`
  already exist with real (partial) implementations.

## Agent context template (analyst — batch 1)
```
Voce e agente de portabilidade do Simplicio Runtime (Rust). Repo: <path>.
MISSAO: identificar codigo REAL (Rust/Python) e testavel (nao ficcao) e onde
encaixar no runtime <target_module>. PASSOS: 1) find . -name '*.rs' -o -name
'*.py' | head -30. 2) Leia arquivos principais. 3) Compare com <target_module>.
Reporte: linguagem, modulos portaveis, gap no runtime, exemplo concreto de
funcao a portar. Responda em portugues. Retorne relatorio <300 palavras.
```

## Agent context template (implementer — batch 2)
```
Voce e agente implementador do Simplicio Runtime (Rust). MISSAO: fortalecer
<target_module> usando o codigo real de <repo_path>. PASSOS: 1) Leia
<target_module> e <repo_path>/src/lib.rs. 2) Identifique a funcao de maior
valor que ADICIONA capacidade (nao duplica). 3) Escreva um plano JSON para
`simplicio edit --plan` (schema v3.5.0: {"file":...,"operations":[{"op":"replace",
"find":"...","with":"..."}]}). 4) Aplique e rode `cargo test --lib <mod>`.
5) Se nao compilar, ajuste o plano. Retorne diff resumido + status do teste.
Responda em portugues.
```

## Advisory lock for append races (std-only, no fs2)
When a shared ledger file is appended by multiple workers (e.g. `hbp::HbpInbox::append`),
the original `.append(true)` open has NO lock → concurrent writes can interleave and
corrupt the chain. Fix without adding a dependency:
```rust
let lock_path = self.db_path.with_extension("jsonl.lock");
let mut lock_file = None;
for _ in 0..1000 {
    match std::fs::OpenOptions::new().create_new(true).write(true).open(&lock_path) {
        Ok(f) => { lock_file = Some(f); break; }
        Err(_) => std::thread::sleep(std::time::Duration::from_millis(2)),
    }
}
// ... do the append ...
drop(lock_file);
let _ = std::fs::remove_file(&lock_path);
```
This is the fix applied to `src/hbp/mod.rs` (ADR-2026-07-09). 11 hbp tests still green.

## Pre-existing test failure check
To confirm a failing test is NOT yours: `git stash` your changes, run the test,
restore with `git stash pop`. In the 2026-07-09 sprint, `profiles::tests::
test_create_and_switch` failed even on a clean tree (filesystem-state dependent) —
pre-existing debt, not regression. Don't block the integration on it.
