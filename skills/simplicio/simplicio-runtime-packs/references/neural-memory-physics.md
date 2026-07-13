# Neural Memory Physics System

Criado em 05/07/2026. Sistema de memória vetorial com física Asolaria.

## Arquitetura

O runtime tem **3 tabelas de memória vetorial** no banco `~/.simplicio/memory/simplicio-memory.sqlite`:

| Tabela | Rows | Propósito |
|--------|------|-----------|
| `memory_vectors` | 37.368 | Tabela nativa do runtime (usada por `memory_v2.rs`) |
| `vector_memory` | 37.368 | Tabela com decay_score + tier + access tracking (populada pelo script) |
| `vec_memory` | 37.368 | ANN index via sqlite-vec vec0 (cosine distance, 256 dims) |

## Constantes físicas (de `asolaria/decay.rs`)

```
λ = 0.02      # decay rate → meia-vida de 35 dias
σ = 0.6       # magnitude de reforço por acesso
μ = 0.04      # decay do reforço de acesso
salience = 1.0
cold_threshold = 0.20
hard_delete_after_days = 180
```

## Fórmula de retention_score

```
retention_score = salience · exp(-λ · age_days) 
                + σ · ln(1 + access_count) · exp(-μ · days_since_access)
```

## Tier consolidation (Karpathy-style)

| Tier | Descrição | Exemplos |
|------|-----------|----------|
| `working` | Sessão atual, estado quente | agent_state, conversation recente |
| `episodic` | Observações, conversas, commits | project_code <500b, git_commit |
| `semantic` | Conhecimento destilado | project_code >=500b, decision, fact |
| `procedural` | Padrões reutilizáveis | skill, skill_catalog, project_skill |

## Embedding

Determinístico, sem LLM: FNV-1a hash sobre unigramas + trigramas → signed buckets 256D → L2-normalize.

```python
# Algoritmo (replicado do Rust vector_memory.rs):
v = [0.0] * 256
for word in split(text):
    h = fnv1a(word)
    v[h % 256] += 1.0 ou -1.0 (baseado no bit 17 do hash)
    for trigram in word.windows(3):
        h = fnv1a(trigram)
        v[h % 256] += sign
norm = sqrt(sum(x²))
if norm > 0: v = [x/norm for x in v]
```

## HBP chain

Toda operação de escrita na memória registra um receipt na tabela `hbp_chain`:
- SHA-256 sobre campos length-prefixed (seq, prev_hash, topic, payload)
- Cada linha prova a anterior (hash chain)
- Status: 81 receipts criados até 05/07/2026

## Comandos

```bash
# Busca híbrida (FTS5 + ANN + rerank)
~/.local/bin/simplicio-recall "query" --top 10
~/.local/bin/simplicio-recall "query" --json

# Alias shell (adicionado ao .zshrc)
recall "query" --top 5

# Recalcular decay manualmente
python3 ~/.simplicio_agent/scripts/decay_recalc.py

# Recalcular decay automático (cron job: 0 */6 * * *)
simplicio cron list  # job_id=7b118e4406cd
```

## Gaps conhecidos

1. `simplicio memory --backend sqlite-vec` — runtime ignora o flag, cai para FTS5
2. `simplicio memory-v2 search --query` — syntax error no hífen do --query
3. `simplicio-recall` é script Python, não comando Rust nativo — ~100x mais lento
4. `simplicio memory` pipeline padrão não usa ANN — só FTS5 lexical
5. Access tracking só funciona no `simplicio-recall`, não no `simplicio memory` padrão
