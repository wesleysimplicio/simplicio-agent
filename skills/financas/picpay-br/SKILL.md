---
name: picpay-br
description: PicPay — carteira digital, pagamentos e serviços
category: financas
---

# Picpay Br Skill

Skill para interagir com o CLI `picpay` via Hermes Agent.

## Pré-requisitos

- CLI instalado via `pip install -e /Users/wesleysimplicio/Projetos/Contribuicao/Brasil/picpay-cli`
- Credenciais de acesso conforme o banco/serviço

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações financeiras via CLI.

### Comandos Disponíveis

```python
# Verificar ajuda do CLI
terminal("picpay --help")

# Comandos específicos (ajustar conforme CLI)
# terminal("picpay balance")
# terminal("picpay statement")
```

### Configuração

```python
# Verificar configuração
terminal("picpay config list")
```

## Observações

- O CLI gerencia autenticação e tokens automaticamente
- Projetos mapeados com llm-project-mapper (AGENTS.md presente)
- Onboarding completo para agentes disponível
