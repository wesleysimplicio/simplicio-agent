---
name: open-finance-br
description: Open Finance Brasil — conectividade bancária padronizada
category: financas
---

# Open Finance Br Skill

Skill para interagir com o CLI `open-finance-br` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/open-finance-br-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("open-finance-br --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("open-finance-br balance")
# terminal("open-finance-br statement")
```

### Configuração

```python
# Verificar configuração
terminal("open-finance-br config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
