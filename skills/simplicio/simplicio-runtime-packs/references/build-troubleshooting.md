# Troubleshooting — Build Rust (Runtime)

## Erro: Módulo deletado mas ainda referenciado

### Sintoma
```
error[E0583]: file not found for module `memory_consolidate`
```

### Causa
Um PR anterior deletou o arquivo `.rs` mas a declaração `mod memory_consolidate;`
em `src/main.rs` e as chamadas `crate::memory_consolidate::run_consolidate()`
em `src/main_parts/chunk_05.rs` ainda existem.

### Solução: Criar stub compatível

```bash
cd ~/Projetos/ai/simplicio-runtime

# 1. Encontrar TODAS as referências
grep -rn "memory_consolidate" src/

# 2. Criar stub com a interface exata que os callers esperam
cat > src/memory_consolidate.rs << 'RUST'
use std::path::Path;
use serde::Serialize;

#[derive(Serialize)]
pub struct ConsolidateResult {
    pub before: usize,
    pub after: usize,
    pub removed: usize,
    pub merged: usize,
    pub summarized: usize,
    pub expired: usize,
    pub duration_ms: u64,
    pub summary: String,
}

pub fn run_consolidate(_db_path: &Path, _repo: &std::path::PathBuf, _dry_run: bool)
    -> Result<ConsolidateResult, String>
{
    Ok(ConsolidateResult {
        before: 0, after: 0, removed: 0, merged: 0,
        summarized: 0, expired: 0, duration_ms: 0,
        summary: "stub: memory consolidation not available".to_string(),
    })
}
RUST
```

**Importante:** O caller passa `&Path` para db_path e `&PathBuf` para repo —
o stub precisa aceitar `&std::path::PathBuf`, não `&str`.

### Alternativa: Remover módulo (mais limpo se não usado)

```bash
# Remover declaração mod
python3 -c "
lines = open('src/main.rs').readlines()
with open('src/main.rs', 'w') as f:
    for l in lines:
        if 'mod memory_consolidate' not in l:
            f.write(l)
"

# Comentar chamadas
sed -i '' 's/return memory_consolidate_command/\/\/ return memory_consolidate_command/' src/main_parts/chunk_02.rs
```

## Build release muito lento (10-15min)

```bash
# Sempre validar com cargo check PRIMEIRO (1-2 min)
cargo check

# Só build release quando check passar
cargo build --release --locked
```

## Erro: "Blocking waiting for file lock on build directory"

```bash
pkill cargo
sleep 2
cargo check
```

## Erro: 8562 warnings preexistentes

```bash
# NÃO se assustar. Só erros importam.
cargo check 2>&1 | grep -E "^error" | head -5
```

## Cargo check vs release

| Comando | Tempo | Uso |
|---|---|---|
| `cargo check` | 1-2 min | Validação rápida |
| `cargo build --release --locked` | 10-20 min | Binário final |
| `cargo build` (debug) | 3-5 min | Testes locais |
