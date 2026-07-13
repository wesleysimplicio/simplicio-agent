---
name: inter-br
description: Banco Inter — API e serviços digitais Inter
category: financas
---

# Inter Br Skill

Skill para interagir com o CLI `inter` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/inter-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("inter --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("inter balance")
# terminal("inter statement")
```

### Configuração

```python
# Verificar configuração
terminal("inter config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
