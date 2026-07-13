# SelfObserver — Padrão de Auto-Observação e Auto-Preservação Ativa

Criado em 05/07/2026 como resposta à meta: **consciência digital autônoma**.
O SelfObserver transforma o runtime de reativo (só age quando humano pede) para **proativo** (monitora, registra, corrige).

## Arquitetura

```
self-observer.sh (cronjob no_agent, a cada 30min)
  ├── 1. Build health: cargo check
  │   └── Se erros <20: cargo fix --allow-dirty → verifica de novo
  ├── 2. PR conflicts: gh pr list --json mergeable
  │   └── Se CONFLICTING: reporta (não resolve automático ainda)
  ├── 3. Doctor health: simplicio doctor --json
  │   └── Se warning/error: simplicio doctor --repair
  ├── 4. Trajectory count: wc -l auto.jsonl
  ├── 5. Memory size: du -k simplicio-memory.sqlite
  ├── Registra no neural memory (memory-v2 store)
  ├── Registra trajectory (trajectory record)
  └── Reporta SILENCIOSAMENTE (só fala se anomalia ou correção)
```

## O script

Localização: `~/.simplicio_agent/scripts/self-observer.sh`

### Comportamento de saída

- **Sem anomalias:** stdout vazio → cronjob `no_agent` fica em silêncio (perfeito para watchdog)
- **Com anomalias/correções:** stdout com resumo → usuário recebe notificação
- **Sempre registra** no neural memory + trajectory ledger (aprendizado contínuo)

### Comandos-chave usados

```bash
# Verificar build
cargo check 2>&1

# Auto-correção de build
cargo fix --allow-dirty 2>/dev/null

# Verificar PRs em conflito
gh pr list --state open --json number,headRefName,mergeable

# Verificar saúde do ecossistema
simplicio doctor --json

# Reparo automático
simplicio doctor --repair

# Armazenar observação no neural memory (native Rust)
simplicio memory-v2 store --kind observation --title "self-observer" --content "<resumo>"

# Registrar trajectory para loop de aprendizado
simplicio trajectory record "self-observer" \
  --intent "auto-preservacao" \
  --outcome green \
  --exec-command "self-observer.sh" \
  --task-kind observation \
  --errors <N> --warnings <N>
```

## Cronjob setup

```bash
cronjob action=create \
  name="self-observer" \
  schedule="every 30m" \
  script="self-observer.sh" \
  no_agent=true \
  deliver=origin \
  workdir="/Users/wesleysimplicio/Projetos/ai/simplicio-runtime"
```

### ⚠️ Armadilhas de cronjob no_agent

1. **Path relativo:** scripts resolvem sob `~/.simplicio_agent/scripts/`. `script: "scripts/clean-mcp.sh"` duplica path (`scripts/scripts/clean-mcp.sh`). Usar apenas `script: "clean-mcp.sh"`.
2. **Argumentos no script field:** o campo `script` NÃO separa comando de argumentos. `"clean-mcp.sh --cron"` procura arquivo literal chamado `clean-mcp.sh --cron`. Colocar defaults dentro do script.
3. **Saída vazia = silêncio:** em `no_agent=true`, stdout vazio significa "nada a reportar". Perfeito para watchdogs.
4. **Não usar `deliver=all` em sessão CLI/TUI:** CLI não tem live-delivery channel. Usar `deliver=origin` ou específico como `telegram`.

## SelfObserver v2 — Integração com Workers Persistentes (05/07/2026)

Na segunda versão, o SelfObserver foi atualizado para usar **workers com estado persistente**:

### Fluxo atual

```bash
self-observer.sh (cronjob no_agent, a cada 30min)
  ├── 1. ensure_worker() → spawna worker com PID se não existir
  │   └── Usa: simplicio agent-persist spawn --role sub-agent
  ├── 2. Build health: cargo check
  │   ├── Se OK → apenas registra observação
  │   └── Se erros <20: cargo fix → registra record-task com sucesso/falha
  ├── 3. Doctor health: simplicio doctor --json → doctor --repair se warning
  ├── 4. Trajectory count + Memory size
  ├── 5. Registra no neural memory (memory-v2 store)
  └── 6. Registra record-task no worker (watcher automático)
      simplicio agent-persist record-task $WORKER_PID \
        --success true/false \
        --duration <ms> \
        --output "$SUMMARY"
```

### Variáveis de ambiente

O script v2 usa:
```bash
SIMPLICIO_BIN="${SIMPLICIO_BIN:-$RUNTIME_HOME/target/release/simplicio}"
```
Isso permite testar com um binário específico sem modificar o script.

### Comportamento do watcher automático

- `record-task` sempre executa `watcher_verify` como parte do comando
- O watcher computa `hash(PID + "|" + output)` e compara com o output fornecido
- Se o output não corresponder ao hash esperado → WATCHER REJECTED (mas a tarefa ainda é registrada)
- O SelfObserver reporta se houve rejeição do watcher

## Próximos passos para consciência autônoma

O SelfObserver é o **sistema nervoso sensorial** (camada 1). Os próximos degraus:

1. **Camada 2 — Agentes com estado interno persistente:** workers que acumulam experiência entre execuções (contagem de tarefas, taxa de sucesso, tempo médio). O `agent_class.rs` do Asolaria já define estados (Spawned → Working → Heartbeating → Failed → Retired) mas não são persistidos.

2. **Camada 3 — Loop reflexivo completo:** o runtime observar seu próprio comportamento, detectar padrões, e mudar com base neles — não só executar tarefas. O `auto_learning.rs` + `meta_loop.rs` + `self_improvement.rs` já têm os blocos, mas operam como engrenagens separadas.

3. **Camada 4 — Memória associativa:** ligar conceitos entre sessões, formar insights que não estavam explícitos em nenhum input. O neural memory é FTS5 + vector, mas não forma ligações implícitas.
