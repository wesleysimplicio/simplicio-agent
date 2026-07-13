#!/usr/bin/env bash
# Continuation: issues 4-6
set -euo pipefail

REPO="${1:-wesleysimplicio/simplicio-runtime}"

create_issue() {
    local title="$1"
    local body="$2"
    local labels="$3"
    echo "Criando: $title"
    gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
    echo "---"
}

# ========================================================================
# ISSUE 4: Pipeline CI/CD
# ========================================================================
create_issue \
"[CI/CD] Pipeline de integração contínua e entrega contínua automatizada" \
'## Contexto

O Simplicio tem gates para commit, orientação, ação, validação e entrega... mas **não tem um CI pipeline que execute tudo automaticamente**. Cada gate é manual, e não há verificação automatizada entre código-fonte e release.

Atualmente:
- `simplicio validate` existe mas nunca é chamado automaticamente
- `simplicio packages update` existe mas não está wireado em nenhum pipeline
- Não há lint, build, test, ou security audit automáticos antes de merge
- Releases são manuais (cargo build --release + upload)

## O que precisa acontecer

1. **`simplicio ci run`** — comando que executa o pipeline completo localmente:
   ```
   simplicio ci run
   ├── lint: cargo clippy -- -D warnings
   ├── build: cargo build --release --locked
   ├── test: cargo test
   ├── security: simplicio security --json
   ├── package: simplicio packages update
   ├── sign: GPG sign do binário
   └── report: sumário em markdown
   ```

2. **GitHub Actions workflow** que chama o binário compilado:
   - `ci.yml` — roda em todo push e PR
   - `release.yml` — quando merge na main, faz auto-release
   - `nightly.yml` — build noturno com testes extended

3. **Auto-release pipeline**:
   - Quando um PR passa por todos os gates → auto-merge
   - CI passa → bump version (semver automático) → cargo build → GitHub Release → publish
   - `simplicio update check/apply` puxa do GitHub Releases

## Integração com gates existentes

```
Commit → Pre-commit Gate → Push → CI Run (lint+build+test+security) → Merge → Release Gate → Auto-Release
```

## Critérios de sucesso

- [ ] `simplicio ci run` executa pipeline completo localmente
- [ ] GitHub Actions CI roda em todo push/PR
- [ ] Auto-release quando merge na main
- [ ] `simplicio update` funciona do GitHub Releases
- [ ] Pipeline falha se algum gate não passar' \
"ci/cd,prioridade-alta,automação"

# ========================================================================
# ISSUE 5: Self-healing real
# ========================================================================
create_issue \
"[SELF-HEALING] Implementar recuperação automática de falhas (crash, lock, deadlock)" \
'## Contexto

O Simplicio crasha frequentemente com:
- `SIGKILL` por estouro de RAM (especialmente com enforcement + multi-agents)
- Lock contention no `repo.lock` (`.simplicio/locks/repo.lock`)
- Deadlock de enforcement (plugin bloqueia tools que o usuário precisa)
- Agentes órfãos de runs interrompidas

Hoje a recuperação é **100% manual**:
```bash
rm -f .simplicio/locks/repo.lock
kill -9 <pid>
# ou reiniciar a sessão
```

## O que precisa acontecer

1. **`simplicio recover --auto`** — recovery automático:
   - Limpa locks órfãos (> 5 minutos sem heartbeat)
   - Mata agents com timeout
   - Restaura estado consistente do `.simplicio/`
   - Gera relatório do que foi limpo

2. **Health endpoint**:
   - Endpoint HTTP que retorna status do runtime
   - Heartbeat dos agents ativos
   - Uso de memória/CPU
   - Integridade dos locks

3. **Watchdog systemd/LaunchAgent**:
   - Reinicia automaticamente em caso de crash
   - Health check periódico
   - Notificação quando auto-recovery não é suficiente

4. **Graceful degradation**:
   - Se RAM > 80%, reduz número de agents (profile: normal → low)
   - Se lock contention, espera com backoff exponencial
   - Se enforcement causa deadlock, bypass automático

## Arquivos afetados

- `src/main.rs` — signal handlers (SIGTERM, SIGINT)
- `src/gateway/runner.rs` — heartbeat endpoint
- `.simplicio/locks/` — lock management
- `Cargo.toml` — dependencies

## Critérios de sucesso

- [ ] `simplicio recover --auto` limpa locks em < 1s
- [ ] Health endpoint retorna status JSON
- [ ] Watchdog reinicia runtime em < 10s após crash
- [ ] Graceful degradation: reduz agents automaticamente em pico de RAM
- [ ] Notificação ao usuário quando recovery falha' \
"self-healing,prioridade-alta,infra"

# ========================================================================
# ISSUE 6: Feature flags e canary releases
# ========================================================================
create_issue \
"[RELEASE] Feature flags para comando experimentais + canary releases (stable/beta/nightly)" \
'## Contexto

Hoje, cada novo comando ou skill do Simplicio é **compilado direto no binário**. Se quebrar, quebra tudo. Não há:

- Feature flags para ativar/desativar comandos experimentais em produção
- Canais de release (stable/beta/nightly)
- Kill switch para rollback rápido de funcionalidades problemáticas

O `Cargo.toml` já tem algumas feature gates (`tui`, `voice`, `async-runtime`) mas não cobre:
- Comandos experimentais
- Skills em desenvolvimento
- Gateways não testados

## O que precisa acontecer

1. **Feature gates no Cargo.toml para tudo que é experimental**:
   ```toml
   [features]
   default = ["stable"]
   stable = ["core", "edit", "gate", "gateway-core"]
   beta = ["stable", "organism", "agent-ipc", "video"]
   nightly = ["beta", "wavespeed", "autonomia", "navegacao"]
   experimental = ["ai-agents", "tui", "voice"]
   ```

2. **`simplicio update check --channel stable|beta|nightly`**:
   - Cada canal tem seu próprio tag de release (v1.0.0-stable, v1.1.0-beta.1)
   - Usuário escolhe o canal
   - Upgrade automático dentro do canal

3. **Kill switch**:
   - Se novo módulo crasha em produção, auto-rollback para versão anterior
   - `simplicio update rollback` restaura último binário que funcionava
   - Flag `--force` para pular kill switch

4. **`simplicio feature list|enable|disable`**:
   - Lista todas as features disponíveis
   - Ativa/desativa em runtime (se possível) ou via rebuild
   - Estado persistido em `.simplicio/config.yaml`

## Critérios de sucesso

- [ ] Feature gates separam stable/beta/nightly
- [ ] `simplicio update check --channel beta` funciona
- [ ] Kill switch: rollback automático em caso de crash na inicialização
- [ ] `simplicio feature list` mostra todas as features
- [ ] Compilação mínima (`--no-default-features`) produz binário < 5MB' \
"release,feature-flags,prioridade-média"

echo ""
echo "=== Issues 4-6 criadas! ==="
