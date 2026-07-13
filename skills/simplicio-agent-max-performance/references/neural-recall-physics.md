# Neural Recall + Física da Memória (Jul 2026)

## Pipeline de busca híbrida: FTS5 lexical + ANN semântica

Desenvolvido para unificar os dois sistemas de busca da memória neural:
- **FTS5** (memory_items_fts) — busca lexical por palavras exatas
- **ANN** (vec_memory via sqlite-vec) — busca semântica por similaridade cosseno 256D

### Arquitetura das tabelas

| Tabela | Função | Engine | Itens |
|---|---|---|---|
| `memory_items` | Fonte de verdade | SQLite puro | 37.368 |
| `memory_items_fts` | Índice lexical | FTS5 | 37.368 |
| `memory_vectors` | Embeddings + acesso tracking | SQLite puro | 37.368 |
| `vector_memory` | Embeddings + decay + tier | SQLite puro | 37.368 |
| `vec_memory` | ANN index | sqlite-vec vec0 | 37.368 |
| `access_log` | Histórico de acessos | SQLite puro | variável |
| `hbp_chain` | Cadeia de hash HBP | SQLite puro | 81+ |

### Física da memória (Asolaria decay.rs)

**Equação de decaimento:**
```
retention_score = salience · e^(-λ · Δt) + σ · ln(1 + access_count) · e^(-μ · days_since_access)
```

| Constante | Valor | Significado |
|---|---|---|
| λ (lambda) | 0.02 | Decaimento temporal — meia-vida 35 dias |
| σ (sigma) | 0.6 | Magnitude do reforço por acesso |
| μ (mu) | 0.04 | Decaimento do reforço por acesso |
| salience_default | 1.0 | Score inicial de um item novo |

### Consolidação em tiers

| Tier | Quantidade | Descrição |
|---|---|---|
| `working` | 165 | Estado atual, sessões ativas |
| `episodic` | 14.814 | Observações, conversas, commits |
| `semantic` | 21.417 | Código, docs, decisões, fatos |
| `procedural` | 972 | Skills, padrões reutilizáveis |

### Comandos

```bash
# Busca híbrida completa (FTS5 + ANN + rerank + access tracking + HBP)
simplicio-recall "query" --top 10
simplicio-recall "query" --top 5 --json

# Recalcular decay manualmente
python3 ~/.simplicio_agent/scripts/decay_recalc.py

# Decay automático a cada 6h
# Cron: decay-recalc (job_id: 7b118e4406cd)

# Runtime native search (apenas FTS5)
simplicio memory "query" --backend sqlite-vec

# Runtime parallel search (FTS5 + brute-force vector)
simplicio memory-v2 search-parallel "query"
```

### Bugs corrigidos

1. **`memory-v2 search-parallel` passava `None` como vetor** — o CLI não convertia a query text para embedding antes de passar para `search_parallel()`. Fix: adicionar `embed_text(query)` de `vector_memory.rs` no `memory_v2_command()`.

2. **`memory_vectors` com model name errado** — populado com `embedding_model='fnv1a-256d'` mas o runtime busca por `embedding_model='default'`. Fix: `UPDATE memory_vectors SET embedding_model='default'`.

3. **`memory --backend sqlite-vec` ignorado** — o flag é aceito mas o runtime sempre cai para FTS5. Ainda pendente de investigação no roteamento de backend.

### Dependências

- `sqlite-vec` — extensão .dylib em `~/.simplicio/ext/vec0.dylib`
- `SIMPLICIO_SQLITE_VEC_PATH` — env var no `.zshrc`
- Python 3.9+ para scripts auxiliares

### Para habilitar em nova máquina

```bash
# 1. Instalar sqlite-vec
pip3 install sqlite-vec
cp /path/to/vec0.dylib ~/.simplicio/ext/vec0.dylib

# 2. Setar env var
echo 'export SIMPLICIO_SQLITE_VEC_PATH="$HOME/.simplicio/ext/vec0.dylib"' >> ~/.zshrc

# 3. Popular índices vetoriais (já feitos, só precisa se for rebuild)
python3 /tmp/populate_vectors.py
