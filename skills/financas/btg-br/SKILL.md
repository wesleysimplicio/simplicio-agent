---
name: btg-br
description: BTG Pactual — investimentos, contas e serviços BTG
category: financas
---

# Btg Br Skill

Skill para interagir com o CLI `btg` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/btg-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("btg --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("btg balance")
# terminal("btg statement")
```

### Configuração

```python
# Verificar configuração
terminal("btg config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
