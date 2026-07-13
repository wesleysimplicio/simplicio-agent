# Asolaria HBI/HBP Bridge Integration

## Repositórios Clonados (Jul 2026)

| Repo | Descrição | Path Local |
|---|---|---|
| [asolaria-hbi-hbp](https://github.com/JesseBrown1980/asolaria-hbi-hbp) | Canonical M2M wire format | `~/Projetos/ai/asolaria-hbi-hbp` |
| [holographic-wormhole-codec](https://github.com/JesseBrown1980/holographic-wormhole-codec) | DBBH→DBWH throat codec | `~/Projetos/ai/holographic-wormhole-codec` |
| [asolaria-agent-memory](https://github.com/JesseBrown1980/asolaria-agent-memory) | Neural memory in Rust, 100B actors in 242s | `~/Projetos/ai/asolaria-agent-memory` |

## Integração no Runtime

O `asolaria-hbi-hbp` foi copiado para `crates/asolaria-bridge/` no workspace do runtime.

**Cargo.toml:**
```toml
asolaria-hbi-hbp = { path = "crates/asolaria-bridge" }
```
Workspace members já incluí via glob `crates/*`.

**src/asolaria/mod.rs** — re-exports:
```rust
pub use asolaria_hbi_hbp::{
    encode_row, parse_row, agt,
    sha256, sha256_hex,
    IdxPointer, ReceiptChain,
    verify_chain, GENESIS
};
```

**src/asolaria/sealed_receipt.rs** — bridge module:
- `sealed_receipt_to_hbp_chain()` — converte SealedReceipt para ReceiptChain
- `verify_evidence_chain()` — verifica chain e extrai metadados
- `evidence_agt()` — AGT-addressing para artefatos de evidência
- Tests: round-trip verification + tamper detection

## HBP Row Format (Canônico)

```
TAG|key=val|key=val|...|json=0
```

- Keys são bare (sem escape)
- Values escapam: `\` → `\\`, `|` → `\p`, newline → `\n`
- `encode_row(tag, &[(k,v)])` / `parse_row(row)` — encode/decode

## AGT Addressing

```
AGT-<sha16>    — 20 chars total
onde sha16 = sha256(content)[..16]
```

- `agt(content)` → `"AGT-3f8a2b1c..."`
- Mesmo conteúdo → mesmo AGT (determinístico)
- Store dereference: envie AGT-<sha16> em vez do conteúdo inteiro

## HBI Index Pointers

```
IDX|pid=AGT-<sha16>|off=<u64>|len=<u64>|json=0
```

O(1) seek para uma row sem parsear o blob inteiro.

## Receipt Chain

```
<row>|prev_event_hash=<64hex>|event_hash=<64hex>
```

- `event_hash = sha256(row + "|prev_event_hash=" + prev)`
- Genesis prev = 64 zeros
- `ReceiptChain::append(row)` → receipt row
- `verify_chain(&[receipts]) → bool`

## Ganhos da Integração

1. **Cross-node verification** — Simplicio ↔ Asolaria verificam evidências
2. **Tamper-evident hash chains** — cada artefato selado
3. **AGT addressing** — 20 chars, content-addressed, determinístico
4. **Zero JSON** — pipe-delimited HBP rows no hot path
5. **Mesmo wire format** — Jesse menciona Simplicio no README oficial

## Pull Requests

- simplicio-runtime PR #2918 — merged em main (Jul 4, 2026)
- simplicio-agent PR #89 — merged em main (SIMPLICIO_AGENT_HOME env var)
