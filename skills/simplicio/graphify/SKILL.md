---
name: graphify
title: Graphify — Knowledge Graph sobre a Memória do Simplicio
description: Transforma a memória do Simplicio (memory_items + embeddings all-MiniLM) em um knowledge graph consultável — nós + arestas, comunidades, god nodes, path/explain/query. Port do conceito Graphify (Graphify-Labs) reusando a infra já existente (neural-recall, vec0).
---

# Graphify (Simplicio)

PORT do conceito **Graphify** (Graphify-Labs): transformar conteúdo em um
*knowledge graph* consultável — entidades (nós) + relações (arestas),
clusterizado em comunidades, com centralidade (god nodes) e navegação
`query` / `path` / `explain`.

## Diagnóstico de partida (2026-07-14)

O Simplicio Agent **já tinha** a metade da infraestrutura, mas faltava a
camada relacional:

| Camada | Estado antes | Onde |
|---|---|---|
| Embeddings reais (all-MiniLM-L6-v2) | ✅ 34.912 vetores | `memory_vectors` |
| Busca híbrida FTS5+ANN | ✅ `neural-recall` | `~/.simplicio_agent/scripts/neural-recall` |
| Tabelas de grafo no schema | ✅ existem | `memory_relationships`, `memory_edges` |
| **Relações populadas** | ❌ **0 arestas** | vazias |

O Graphify preenche exatamente esse buraco: **extrai arestas e mede o grafo**.

## O que este skill faz

1. **Build determinístico (0 tokens)** — `graphify_build.py` reusa os
   embeddings JÁ computados e deriva arestas por:
   - **co-referência**: mesmo repo / arquivo / pasta (`same_repo`, `same_file`, `same_dir`)
   - **símbolo**: `def`/`class`/`import`/`call` colocalizados no código (`calls`, `imports`)
   - **semântica**: kNN por cosseno sobre os embeddings (`semantic_neighbor`)
2. **Métricas de grafo** — hub_score por nó, label-propagation em comunidades,
   god nodes, conexões surpreendentes (arestas semânticas entre comunidades).
3. **Persistência** — popula `memory_relationships` (grafo vivo) + `graph.json`
   (cache persistente) + `GRAPH_REPORT.md` + vault Obsidian.
4. **Consulta** — `graphify_query.py`: `query` (traversal + hops), `path`
   (BFS menor caminho), `explain` (vizinhança do nó), `report`.

## Como usar

```bash
# Build completo (determinístico, sem LLM)
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_build.py

# Smoke test em 2000 itens (validar antes do build full)
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_build.py --limit 2000 --dry-run

# Consultar
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_query.py query "retry policy" --hops 2
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_query.py path "code:x:a.py" "code:x:b.py"
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_query.py explain "skill:simplicio-runtime:graphify"
python3 ~/.simplicio_agent/skills/simplicio/graphify/scripts/graphify_query.py report
```

## Integração com neural-recall

`neural-recall` acha nós por similaridade; o Graphify **expande o contexto**
seguindo arestas do grafo (1-hop/2-hop). É o equivalente Simplicio ao
`/graphify query` do Graphify original — em vez de reler arquivos, navega o grafo.

## Modo deep (opcional, com tokens)

`--mode deep` habilita inferência de arestas IMPLÍCITAS via LLM
(OpenRouter `tencent/hy3:free`). Requer `OPENROUTER_API_KEY`. Sem credencial,
cai automaticamente no determinístico (já cobre a maioria das relações reais).

## Verificação

- `SELECT COUNT(*) FROM memory_relationships` deve subir de 0 após o build.
- `GRAPH_REPORT.md` lista god nodes e conexões surpreendentes.
- `graph.json` é consultável sem reler 35k itens.
