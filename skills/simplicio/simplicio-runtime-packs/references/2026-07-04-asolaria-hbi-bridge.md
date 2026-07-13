# Asolaria HBI/HBP Bridge Integration (04/07/2026)

Integrated JesseBrown1980's canonical HBI/HBP bridge codec into the Simplicio runtime.

## O que foi feito

1. **Clonado** `asolaria-hbi-hbp` (https://github.com/JesseBrown1980/asolaria-hbi-hbp) para `~/Projetos/ai/`
2. **Copiado** como crate workspace em `~/Projetos/ai/simplicio-runtime/crates/asolaria-bridge/`
3. **Adicionado** como dependência no `Cargo.toml`:
   ```
   asolaria-hbi-hbp = { path = "crates/asolaria-bridge" }
   ```
4. **Re-exportado** no módulo `asolaria` do runtime (`src/asolaria/mod.rs`):
   ```rust
   pub use asolaria_hbi_hbp::{encode_row, parse_row, agt, sha256, sha256_hex, IdxPointer, ReceiptChain, verify_chain, GENESIS};
   ```

## O que o bridge expõe

| Função/Tipo | Descrição |
|---|---|
| `encode_row(tag, fields)` | Codifica HBP row: `TAG\|k=v\|...\|json=0` |
| `parse_row(row)` | Parseia de volta para `(tag, fields)` |
| `agt(content)` | Content address: `AGT-<sha16>` (20 chars) |
| `sha256(data)` | SHA-256 puro Rust, zero deps |
| `sha256_hex(data)` | SHA-256 em hex (64 chars) |
| `IdxPointer { pid, off, len }` | HBI byte-offset pointer (`.hbi` sidecar) |
| `ReceiptChain::append(row)` | Append-only hash chain: `event_hash=sha256(row+prev)` |
| `verify_chain(receipts)` | Verifica cadeia completa de receipts |
| `GENESIS` | "000...0" (64 zeros) — hash do estado inicial |

## Por que isso importa

O README do `asolaria-hbi-hbp` menciona **Simplicio** explicitamente:
> "Two machines (e.g. an Asolaria node and a Simplicio node) talk to each other in HBP tuple rows, json=0, content-addressed by sha256, with hash-chained receipts"

Isso significa que agora o runtime pode:
- Produzir receipts compatíveis com o formato canônico Asolaria
- Usar `AGT-<sha16>` para referenciar conteúdo entre nós
- Trocar HBP rows diretamente com nós Asolaria

## Próximos passos potenciais

- Conectar `sealed_receipt.rs` para usar `ReceiptChain` do bridge
- Adicionar HBI index pointers nos outputs de evidência
- Criar endpoint M2M para troca de HBP rows entre nós Simplicio ↔ Asolaria
