# Populate Vector Memory — Physics-Based Script

Script de população da `vector_memory` com embeddings FNV-1a 256D + decay + tiers + HBP chain.

## Localização sugerida

`/tmp/populate_vectors.py` (fora do repo gerenciado pelo Simplicio plugin).

## Dependências

- Python 3 stdlib apenas (sqlite3, hashlib, struct, re, time)
- sqlite-vec `.dylib` em `~/.simplicio/ext/vec0.dylib`
- `SIMPLICIO_SQLITE_VEC_PATH` setada (ou `~/.zshrc`)

## Algoritmo

```
para cada item em memory_items (37K):
  1. text = f"{kind}: {title}\n{content[:2000]}"
  2. ts = parse_created_at(item)
  3. decay = SALIENCE_DEFAULT * exp(-LAMBDA * age_days)
            + SIGMA * log1p(access) * exp(-MU * days_since_access)
  4. tier = classify(kind, len, decay)
  5. emb = embed_text(text)  # FNV-1a, 256d, L2-normalized
  6. weight = decay if decay > 0.20 else decay * 0.1
  7. INSERT INTO vector_memory

após todos os batches:
  - DROP + CREATE vec_memory (vec0 virtual table)
  - INSERT items com decay > 0.05
```

## HBP Chain

Cadabatch gera um receipt SHA-256:

```python
def hbp_hash(seq, prev_hash, topic, payload):
    h = hashlib.sha256()
    for field in [str(seq), prev_hash, topic, payload]:
        h.update(len(field).to_bytes(8, 'little'))
        h.update(field.encode())
    return h.hexdigest()
```

Tabela `hbp_chain`:
- seq INTEGER PK
- topic TEXT
- payload TEXT
- prev_hash TEXT (hash da linha anterior)
- hash TEXT UNIQUE (SHA-256 content-addressed)
- created_at TEXT

Genesis: `(0, 'genesis', 'vector_memory_populate', 'genesis', hbp_hash(0, 'genesis', 'genesis', ...))`

## vec0 ANN (sqlite-vec)

```sql
CREATE VIRTUAL TABLE vec_memory USING vec0(
    embedding float[256] distance_metric=cosine,
    id    text,
    text  text,
    ts    integer,
    tier  text
);
```

⚠️ **Não incluir coluna `weight`** — sqlite-vec não suporta colunas extras além de embedding + metadata.

## Performance Esperada

- ~1.300 embeddings/s em M1/M2/M3 (determinístico, zero LLM)
- ~27s para 37K itens
- ~217MB no disco (embeddings + dados brutos + índices)

## Verificação pós-população

```sql
SELECT COUNT(*) FROM memory_items;        -- total fontes
SELECT COUNT(*) FROM vector_memory;        -- embeddings indexados
SELECT COUNT(*) FROM vec_memory;           -- ANN index
SELECT tier, COUNT(*) FROM vector_memory GROUP BY tier;
SELECT MIN(decay_score), AVG(decay_score), MAX(decay_score) FROM vector_memory;
SELECT COUNT(*) FROM hbp_chain;            -- receipts
```
