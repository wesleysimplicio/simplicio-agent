#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"

ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
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
