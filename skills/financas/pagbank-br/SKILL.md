---
name: pagbank-br
description: PagBank — pagamentos, carteira e serviços PagSeguro
category: financas
---

# Pagbank Br Skill

Skill para interagir com o CLI `pagbank` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/pagbank-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("pagbank --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("pagbank balance")
# terminal("pagbank statement")
```

### Configuração

```python
# Verificar configuração
terminal("pagbank config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
