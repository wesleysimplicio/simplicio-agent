#!/usr/bin/env bash
# Create all Simplicio improvement issues on GitHub
# Usage: bash ~/.hermes/skills/fix-enforcement/scripts/create-issues.sh
set -euo pipefail

REPO="${1:-wesleysimplicio/simplicio-runtime}"

echo "=== Criando issues no $REPO ==="
echo ""

create_issue() {
    local title="$1"
    local body="$2"
    local labels="$3"
    echo "Criando: $title"
    gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
    echo "---"
}

# ========================================================================
# ISSUE 1: Modularizar monólito
# ========================================================================
create_issue \
"[REFATORAÇÃO] Modularizar monólito: extrair main.rs (84K+ linhas) em crates do workspace Cargo" \
'## Contexto

O `main.rs` do Simplicio tem **84K+ linhas** com **290 match arms de dispatch** em um único arquivo. Isso torna o código:

- **Difícil de navegar** — qualquer mudança exige scroll por milhares de linhas
- **Propenso a conflitos de merge** — dois PRs tocando o dispatch central = conflito garantido
- **Lento para compilar** — tocar um comando recompila o monólito inteiro
- **Impossível de testar em isolamento** — não há boundaries claros entre módulos

## O que precisa acontecer

1. **Extrair grupos de comando em crates separadas** no workspace Cargo:
   - `simplicio-gateway` — gateways de comunicação (Telegram, Discord, WhatsApp...)
   - `simplicio-edit` — edição determinística (edit, mechanical-edit, test-gated-edit)
   - `simplicio-agents` — dispatch de agentes, organism, delegate
   - `simplicio-security` — gates, guardians, enforcement
   - `simplicio-savings` — savings report, token tracking
   - `simplicio-core` — runtime map, orient, contracts

2. **Cada crate precisa**:
   - Interface pública bem definida (pub fn, pub struct, pub trait)
   - Dependências explícitas (Cargo.toml próprio)
   - Testes unitários próprios
   - Feature gates independentes

3. **main.rs vira um dispatch thin** que só roteia comandos para as crates

## Critérios de sucesso

- [ ] Workspace Cargo com 5+ crates
- [ ] main.rs < 500 linhas (só dispatch thin)
- [ ] Compilação incremental: mudar 1 crate não recompila as outras
- [ ] Cada crate tem `cargo test` próprio
- [ ] `simplicio --help` continua funcionando com todos os comandos

## Referências

- Cargo Workspaces: https://doc.rust-lang.org/book/ch14-03-cargo-workspaces.html
- Arquivos afetados: `src/main.rs`, `Cargo.toml`
- ~277 arquivos .rs no total, ~84K linhas só no dispatch' \
"refatoração,prioridade-alta"

# ========================================================================
# ISSUE 2: Zero testes
# ========================================================================
create_issue \
"[TESTES] Implementar testes automatizados em todo o runtime" \
'## Contexto

O Simplicio runtime tem **zero testes automatizados** — nem unitários, nem integração, nem E2E. O código usa `#![allow(dead_code)]` em **50+ módulos** porque ninguém sabe o que está vivo ou morto.

Isso significa que:
- Toda refatoração é um voo cego
- Regressões só são descobertas em produção
- Código morto se acumula sem consequências
- Novos contribuidores não têm rede de segurança

## O que precisa acontecer

### Fase 1: Testes de unidade (crítico)
Cobrir os módulos centrais que são mais estáveis e têm lógica complexa:
- `gate_command.rs` — sistema de gates (classify, status, allow, deny)
- `security_command.rs` — supply-chain audit
- `hooks_command.rs` — shell hooks
- `edit/` — edição determinística
- `schemas/` — validação de schemas JSON

### Fase 2: Testes de snapshot CLI
- Cada comando CLI produz snapshot da saída
- `simplicio --help`, `simplicio runtime map --for-llm`, `simplicio status`
- Regression detection em saída de terminal

### Fase 3: Testes de integração
- Pipeline completo: `simplicio edit --plan` → `simplicio validate`
- Criação de repo temporário, execução de comandos, verificação de resultado
- Gateway smoke tests (mock HTTP)

### Fase 4: CI integration
- `cargo test` roda em todo PR
- `cargo clippy` sem warnings
- Cobertura mínima: 30% (Fase 1), 50% (Fase 2), 70% (Fase 3)

## Formato

Usar Rust testing padrão (`#[cfg(test)] mod tests`). Cada módulo tem seus testes ao lado do código.

## Critérios de sucesso

- [ ] `cargo test` roda sem falhas
- [ ] Cobertura > 30%
- [ ] Todos os comandos principais têm snapshot test
- [ ] Pipeline de integração: edit → validate roda de ponta a ponta
- [ ] `#![allow(dead_code)]` reduzido de 50+ módulos para < 10' \
"testes,prioridade-alta"

# ========================================================================
# ISSUE 3: Agent IPC
# ========================================================================
create_issue \
"[AGENT-IPC] Implementar comunicação inter-processos (agent-ipc/v1) — schema existe há 8 meses sem implementação" \
'## Contexto

O schema `agent-ipc/v1` existe como arquivo `.json` em `schemas/` há **mais de 8 meses**, mas **nunca foi implementado**. Isso significa que:

- Os **23 módulos em `src/organism/`** (arquitetura de "organismo digital") são código não testado ou morto — não há comunicação real entre processos Simplicio
- `simplicio agents delegate` provavelmente não funciona em produção multi-processo
- O ecossistema de agentes paralelos (64-600 workers) não tem backbone de comunicação
- Schemas como `agent-queue-item`, `agent-lease`, `agent-escalation-policy` existem mas nunca foram exercitados

## O que precisa acontecer

1. **Implementar agent-ipc via stdin/stdout JSON-RPC** (leve, zero dependências externas):
   - Protocolo request/response com message IDs
   - Suporte a notificações (fire-and-forget)
   - Timeout e retry configuráveis
   - Autenticação via token shared

2. **Wirear no `organism/`**:
   - Cada módulo do organismo se comunica via agent-ipc
   - Heartbeat entre agents
   - Message routing baseado em capability

3. **Atualizar schemas**:
   - `agent-ipc/v1` — tornar protocolo real com exemplos
   - `agent-lease/v1` — implementar lease system
   - `agent-escalation-policy/v1` — implementar escalação

## Critérios de sucesso

- [ ] Dois processos Simplicio se comunicam via agent-ipc
- [ ] `simplicio agents delegate` funciona com workers reais
- [ ] organism/ tem testes de comunicação
- [ ] Schemas antigos atualizados ou removidos
- [ ] Documentação do protocolo' \
"agent-ipc,prioridade-alta,arquitetura"

echo ""
echo "=== Primeiro lote criado! ==="
echo "Repo: $REPO"'
