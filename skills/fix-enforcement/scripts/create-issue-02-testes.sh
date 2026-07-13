#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
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

## Critérios de sucesso

- [ ] `cargo test` roda sem falhas
- [ ] Cobertura > 30%
- [ ] Todos os comandos principais têm snapshot test
- [ ] Pipeline de integração: edit → validate roda de ponta a ponta
- [ ] `#![allow(dead_code)]` reduzido de 50+ módulos para < 10' \
"testes,prioridade-alta"
