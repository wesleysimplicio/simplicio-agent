---
name: bb-br
description: Banco do Brasil — API e serviços bancários BB
category: financas
---

# Bb Br Skill

Skill para interagir com o CLI `bb` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/bb-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("bb --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("bb balance")
# terminal("bb statement")
```

### Configuração

```python
# Verificar configuração
terminal("bb config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
