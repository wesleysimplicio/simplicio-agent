# sqlite-vec Activation — ANN Semantic Search no Runtime

O runtime suporta sqlite-vec como backend de memória neural com ANN (Approximate Nearest Neighbor) search desde `vector_memory.rs`. Quando ativo, substitui a busca FTS5 lexical por busca semântica com cosign similarity.

## Instalação

```bash
# 1. Instalar o pacote Python (fornece a .dylib)
pip3 install sqlite-vec

# 2. Localizar a extensão compilada
ls ~/Library/Python/3.9/lib/python/site-packages/sqlite_vec/vec0.dylib

# 3. Copiar para o diretório onde o runtime procura
mkdir -p ~/.simplicio/ext
cp ~/Library/Python/3.9/lib/python/site-packages/sqlite_vec/vec0.dylib ~/.simplicio/ext/vec0.dylib
```

## Ativação

O runtime carrega a extensão por ordem de precedência:
1. `SIMPLICIO_SQLITE_VEC_PATH` env var
2. `SQLITE_VEC_PATH` env var
3. `~/.simplicio/ext/vec0.dylib` (fallback)

```bash
# Teste com env var explícita
SIMPLICIO_SQLITE_VEC_PATH=~/.simplicio/ext/vec0.dylib \
  simplicio memory status --json --repo . | python3 -c "
import json,sys
d=json.load(sys.stdin)
for b in d.get('backend_order',[]):
    print(f'  #{b[\"priority\"]} {b[\"id\"]}: {b[\"status\"]}')
"
```

**Antes:** `#2 sqlite-vec: optional`
**Depois:** `#2 sqlite-vec: available`

## Permanência

Adicionar ao `~/.zshrc`:
```bash
export SIMPLICIO_SQLITE_VEC_PATH="$HOME/.simplicio/ext/vec0.dylib"
```

## Verificação

```bash
# Status completo com vec0 ativo
SIMPLICIO_SQLITE_VEC_PATH=~/.simplicio/ext/vec0.dylib simplicio memory status --json --repo .
```

O runtime cria a tabela virtual `vec_memory` com:
- `embedding float[256] distance_metric=cosine`
- `id text, text text, ts integer`

## Memory Prune + VACUUM

Quando a memória neural acumula itens corrompidos ou antigos:

```bash
# 1. Identificar itens problemáticos
sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite "
SELECT kind, COUNT(*), MIN(created_at), MAX(created_at)
FROM memory_items GROUP BY kind ORDER BY COUNT(*) DESC;
"

# 2. Remover itens mal formatados
sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite "
DELETE FROM memory_items WHERE kind='--kind' OR kind='';
"

# 3. Forçar checkpoint WAL
sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"

# 4. Recuperar espaço (pode levar alguns segundos para DBs grandes)
sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite "VACUUM;"

# 5. Verificar resultado
ls -lh ~/.simplicio/memory/simplicio-memory.sqlite
```

**Savings típica:** 121MB → 96MB (~25MB/20% recuperado após prune de 1 item mal formatado + VACUUM).

## Arquitetura

O código que carrega a extensão está em `src/vector_memory.rs`:

```rust
fn try_load_vec_extension(conn: &Connection) -> Result<(), String> {
    let path = std::env::var("SIMPLICIO_SQLITE_VEC_PATH")
        .or_else(|_| std::env::var("SQLITE_VEC_PATH"))
        .unwrap_or_else(|_| format!("{}/.simplicio/ext/vec0.dylib", home));
    // SAFETY: LoadExtensionGuard + load_extension
    let _guard = unsafe { LoadExtensionGuard::new(conn) }?;
    unsafe { conn.load_extension(path, None) }?;
    Ok(())
}
```

## Referências no código

- `src/vector_memory.rs` — `SqliteVectorStore` com `vec0_available: bool`
- `src/memory_v2.rs` — integração com LanceDB/sqlite-vec
- `src/main_parts/chunk_02.rs` — parsing do backend name `sqlite-vec`
- `~/.simplicio/ext/vec0.dylib` — local canônico da extensão
