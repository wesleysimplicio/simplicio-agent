# Defaults de Performance — Simplicio Agent

Este documento mapeia todos os módulos de performance do Simplicio Agent,
suas condições de ativação e como verificar o estado atual.

## Resumo executivo

A maioria dos módulos de performance fica **desativada na instalação padrão**
por depender de extras opcionais (`pip install simplicio-agent[fast]`) ou de
build Rust. Na instalação base (`pip install simplicio-agent`), o comportamento
é equivalente ao Hermes upstream.

## Mapa de módulos e condições de ativação

| Módulo | Arquivo | Condição de ativação | Fallback padrão |
|---|---|---|---|
| Fast JSON (orjson) | `agent/serde/`, `agent/_fastjson.py` | `pip install orjson` ou extra `[fast]` | `json` stdlib |
| Fast JSON (msgspec) | `agent/serde/` | `pip install msgspec` ou extra `[fast]` | `json` stdlib |
| Token estimator (tiktoken) | `agent/tokens/fast_estimator.py` | `pip install tiktoken` | `len(text) // 4` |
| Rust extension (simplicio_fast) | `agent/_simplicio_fast.py` | `cargo build` + `HAVE_RUST=1` | Python puro |
| Streaming hot-path | `agent/transports/chat_completions.py` | sempre ativo | — |
| Warm daemon | `agent/gateway/` | `simplicio-agent daemon start` | cold start |
| Token saver plugin | `agent/plugins/token_saver.py` | `SIMPLICIO_TOKEN_SAVER=1` | desativado |
| Telemetria | `agent/telemetry/` | `SIMPLICIO_TELEMETRY=1` | desativado |
| Iteration budget | `agent/iteration_budget.py` | `budget_config` presente | sem limite |
| Lazy schema | `agent/lazy_schema/` | `SIMPLICIO_LAZY_SCHEMA=1` | schema completo |
| Distributed worker | `agent/distributed/` | `SIMPLICIO_DISTRIBUTED=1` | single-process |
| Working set cache | `agent/context/` | sempre ativo (LRU em memória) | — |

## Como verificar o estado atual

```bash
# Diagnóstico completo
simplicio doctor --json

# Verifica HAVE_RUST (Rust extension ativa?)
python3 -c "from agent._simplicio_fast import HAVE_RUST; print('HAVE_RUST:', HAVE_RUST)"

# Verifica orjson
python3 -c "import orjson; print('orjson OK')"

# Verifica tiktoken
python3 -c "import tiktoken; print('tiktoken OK')"

# Status do daemon
simplicio-agent daemon status
```

## Como ativar todos os módulos

```bash
# Instala extras de performance
pip install "simplicio-agent[fast]"

# Ativa variáveis de ambiente
export SIMPLICIO_TOKEN_SAVER=1
export SIMPLICIO_TELEMETRY=1
export SIMPLICIO_LAZY_SCHEMA=1
export SIMPLICIO_DISTRIBUTED=1  # multi-process

# Inicia daemon (warm start)
simplicio-agent daemon start

# Verifica
simplicio doctor --json
```

## Toggles por variável de ambiente

| Variável | Efeito | Default |
|---|---|---|
| `SIMPLICIO_TOKEN_SAVER` | Ativa compressão de prompts | `0` |
| `SIMPLICIO_TELEMETRY` | Ativa coleta de métricas | `0` |
| `SIMPLICIO_LAZY_SCHEMA` | Carrega schemas sob demanda | `0` |
| `SIMPLICIO_DISTRIBUTED` | Ativa workers distribuídos | `0` |
| `SIMPLICIO_GATE_SKIP` | Pula pre-commit gate (CI/dev) | `0` |
| `HAVE_RUST` | Flag de detecção da extensão Rust | auto |

## Checklist de revisão (AC da issue #10)

- [x] Mapeados todos os módulos e suas condições de ativação
- [x] Documentado como verificar o estado atual
- [x] Documentado como ativar todos os módulos de uma vez
- [x] Listados todos os toggles de ambiente
- [x] Testes de documentação adicionados em `tests/test_perf_defaults_doc.py`

## Referências

- `agent/serde/` — fast JSON (orjson/msgspec)
- `agent/tokens/` — estimativa de tokens (tiktoken)
- `agent/_simplicio_fast.py` — bridge para extensão Rust
- `agent/telemetry/` — stack de observabilidade
- `agent/plugins/token_saver.py` — plugin de economia de tokens
- `agent/context/` — working set LRU + prefetch pipeline
- `docs/roadmap/SIMPLICIO-ROADMAP.md` — roadmap de performance completo
