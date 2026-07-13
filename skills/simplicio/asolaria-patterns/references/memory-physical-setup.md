# Memory Physical Layer — Setup Reference

Implantação da camada física de memória neural com Asolaria decay + HBP chain + sqlite-vec ANN.

## Pré-requisitos

- sqlite-vec: `pip3 install sqlite-vec`
- Runtime v3.0.1+ com `SIMPLICIO_SQLITE_VEC_PATH` setado

## Scripts Criados

| Script | Localização | Função |
|---|---|---|
| `populate_vectors.py` | `~/.simplicio_agent/scripts/` | Popula vector_memory + vec0 + HBP chain |
| `semantic_recall.py` | `~/.simplicio_agent/scripts/` | Busca ANN com tracking de acesso |
| `decay_recalc.py` | `~/.simplicio_agent/scripts/` + `~/.hermes/scripts/` | Recalcula decay scores (cron 6h) |

## Cron Jobs

| Job | Schedule | Script |
|---|---|---|
| `decay-recalc` | `0 */6 * * *` | `decay_recalc.py` (no_agent) |

## Tabelas Criadas no Banco Neural

### `vector_memory`
```sql
CREATE TABLE vector_memory (
    id        TEXT PRIMARY KEY,
    text      TEXT NOT NULL,
    embedding BLOB NOT NULL,      -- 256 f32 little-endian
    ts        INTEGER NOT NULL,   -- unix seconds
    decay_score REAL DEFAULT 1.0, -- retention score
    tier      TEXT DEFAULT 'episodic',  -- working/episodic/semantic/procedural
    weight    REAL DEFAULT 1.0,   -- decay-scaled weight for brute-force fallback
    access_count INTEGER DEFAULT 0,
    last_access_at INTEGER DEFAULT 0
);
```

### `access_log`
```sql
CREATE TABLE access_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id   TEXT NOT NULL,
    query     TEXT NOT NULL,
    score     REAL NOT NULL,
    tier      TEXT,
    accessed_at INTEGER NOT NULL
);
```

### `vec_memory` (virtual table via sqlite-vec)
```sql
CREATE VIRTUAL TABLE vec_memory USING vec0(
    embedding float[256] distance_metric=cosine,
    id    text,
    text  text,
    ts    integer,
    tier  text
);
```

### `hbp_chain`
```sql
CREATE TABLE hbp_chain (
    seq       INTEGER PRIMARY KEY,
    topic     TEXT NOT NULL,
    payload   TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);
```

## Estados Verificados

| Data | Itens indexados | Tempo | Velocidade | HBP receipts | Tier distribution |
|---|---|---|---|---|---|
| 2026-07-05 | 37.368 | 27.1s | 1.378/s | 77 | working:165 episodic:14.814 semantic:21.417 procedural:972 |

## Comandos Úteis

```bash
# Recarregar tudo (se memória foi limpa)
python3 ~/.simplicio_agent/scripts/populate_vectors.py

# Busca semântica
python3 ~/.simplicio_agent/scripts/semantic_recall.py "query" 10

# Recalcular decay manualmente
python3 ~/.simplicio_agent/scripts/decay_recalc.py

# Verificar estado
sqlite3 ~/.simplicio/memory/simplicio-memory.sqlite "
SELECT 'items:', COUNT(*) FROM memory_items;
SELECT 'vectors:', COUNT(*) FROM vector_memory;
SELECT 'ANN:', COUNT(*) FROM vec_memory;
SELECT 'HBP:', COUNT(*) FROM hbp_chain;
"
```
