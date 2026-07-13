# Asolaria — Test Gap Analysis

> Gerado automaticamente em 2026-07-05
> Alvo: `src/asolaria/` (28 arquivos Rust)

## Checklist rápido — qual arquivo precisa de teste?

Use `grep -c '#\[cfg(test)\]' src/asolaria/<arquivo>` para verificar se um arquivo já tem testes. Se retornar `0`, não tem teste algum.

## Comando para auditoria completa

```bash
cd /Users/wesleysimplicio/Projetos/ai/simplicio-runtime
for f in src/asolaria/*.rs; do
  has_tests=$(grep -c '#\[cfg(test)\]' "$f" 2>/dev/null)
  has_pub=$(grep -c '^pub ' "$f" 2>/dev/null)
  echo "$(basename $f): pub_markers=$has_pub test_mods=$has_tests"
done
```

## Arquivos com cobertura (16)

| Arquivo | Funções pub | Test mods |
|---|---|---|
| `agent_class.rs` | 4 | 1 |
| `agent_state.rs` | 4 | 1 |
| `attack_verify.rs` | 7 | 2 |
| `consolidator.rs` | 4 | 1 |
| `cosign_chain.rs` | 4 | 1 |
| `decay.rs` | 2 | 1 |
| `fabric_node.rs` | 3 | 1 |
| `fedenv.rs` | 12 | 1 |
| `glyph_genesis.rs` | 6 | 1 |
| `hookwall.rs` | 8 | 1 |
| `nest_prime.rs` | 5 | 1 |
| `observation.rs` | 4 | 1 |
| `pid.rs` | 20 | 1 |
| `sealed_receipt.rs` | 3 | 1 |
| `tier.rs` | 8 | 1 |
| `tiered_memory.rs` | 1 | 1 |

## Arquivos SEM cobertura (10) — por prioridade

### 🔴 store_ops.rs — 18 funções públicas, 0 testes

Camada de persistência SQLite. Risco de corrupção de dados. Prioridade máxima.

Funções: `upsert_page`, `get_or_create_workspace`, `get_or_create_project`, `upsert_pages_batch`, `begin_session`, `end_session`, `insert_observation`, `store_embedding`, `store_embeddings`, `bump_access_for_pages`, `soft_delete_for_decay`, `hard_delete_decayed_pages`, `insert_handoff`, `accept_handoff`, `reorg_sessions`, `rename_project`, `insert_wiki_migration`, `purge_project`.

### 🟡 hooks.rs — 7 funções públicas, 0 testes

Pipeline de hooks do agente. Perda de observações se falhar.

Funções (inline mods): `Sanitized::new`, `Sanitized::into_inner`, `Sanitized::redacted_count`, `Sanitizer::new`, `Sanitizer::sanitize`, `hook_router`, `synthesize_session_page`.

### 🟢 Arquivos com apenas tipos (cobertura indireta suficiente)

- `error.rs` — `AsolariaError` enum, `AsolariaResult<T>` (testável indiretamente)
- `handoff.rs` — `HandoffState`, `NewHandoff`, `Handoff` structs
- `ids.rs` — `AsolariaIdError`, `AgentKind`, `PagePath`
- `reader.rs` — 14 structs de leitura (sem funções hoje)
- `types.rs` — `Signature`, `SyscallErr`, `HookwallVerdict`, `AccessTier`
- `mod.rs` — Module declarations + re-exports (não aplicável)
- `prism_bridge.rs` / `wormhole_bridge.rs` — Re-exports de crate externa (não aplicável)

## Como executar testes existentes

```bash
cd /Users/wesleysimplicio/Projetos/ai/simplicio-runtime
cargo test --lib asolaria       # testes inline
cargo test --lib asolaria -- --nocapture  # com output
cargo test asolaria::           # prefix match (ex: cargo test asolaria::store_ops)
```

## Nota sobre o Simplicio plugin

A partir do Hermes Agent com plugin Simplicio ativo, os tools nativos `search_files`, `read_file` e `write_file` são bloqueados dentro do repositório gerenciado. Use terminal com `grep`, `cat`, `find` como alternativa:

```bash
# Listar arquivos
find src/asolaria/ -name '*.rs' -type f | sort

# Extrair funções públicas
grep -n 'pub fn' src/asolaria/arquivo.rs

# Verificar testes existentes
grep -c '#\[cfg(test)\]' src/asolaria/arquivo.rs

# Extrair assinaturas completas (incluindo multi-linha)
awk '/^pub fn/ {print NR": "$0}' src/asolaria/arquivo.rs
```
