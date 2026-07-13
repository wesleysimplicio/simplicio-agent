# Version OOM Fix — `simplicio version --json` SIGKILL

## Problema
`simplicio version --json` morria com SIGKILL (exit 137) por construir manifesto de ~12KB via `format!()` com 30+ interpolações eager.

## Causa Raiz
`src/main_parts/chunk_09.rs` (~737): `format!()` chamava `identity_policy_json()`, `entitlement_policy_json()`, `auto_update_policy_json()`, `component_manifest_json()` × 4 — tudo eager, mesmo se só queria o campo `version`.

## Fix Aplicado (PR #2849 — MERGEADO)
1. **`src/main_parts/chunk_15.rs`** — OnceLock caching para `identity_policy_json()` e `entitlement_policy_json()`
2. **`src/main_parts/chunk_09.rs`** — `serde_json::json!()` + OnceLock para seções pesadas

## Erros comuns durante fix

| Erro | Causa | Fix |
|---|---|---|
| E0425 | `model_checked` não definido | `static MODEL_CHECKED: AtomicBool` |
| E0433 | `Ordering` sem import | `std::sync::atomic::Ordering::SeqCst` |
| E0308 | unclosed delimiter no OnceLock | `}.clone();` (ponto e vírgula + chave fechando) |

## Padrão OnceLock correto
```rust
fn identity_policy_json() -> String {
    static CACHED_IDENTITY: OnceLock<String> = OnceLock::new();
    CACHED_IDENTITY
        .get_or_init(|| { format!("...") })
        .clone();  // ← ; OBRIGATORIO
}  // ← } OBRIGATORIO
```

Issue: #2842. Status: ✅ Mergeado via PR #2849.
