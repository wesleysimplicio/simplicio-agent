---
name: matera-br
description: CLI para API Matera Edge Services — pagamentos, contas, transações, PIX e dados bancários no Brasil
category: financas
---

# Matera Brasil Skill

Skill para interagir com a **API Matera Edge Services** através do CLI `matera`.

## Pré-requisitos

- CLI `matera` instalado via `pip install -e ~/Projetos/Contribuicao/Brasil/matera-cli`
- Credenciais de acesso (usuário e senha fornecidos pela Matera)

## Uso com Hermes Agent

Esta skill permite que o Hermes Agent execute operações na plataforma Matera.

### Autenticação

```python
# Login (salva token em ~/.hermes2/scripts/matera-cli/token.json)
terminal("matera login --username USUARIO --password SENHA")
```

**Importante:** A senha da Matera deve ser fornecida como SHA-256. Se o usuário fornecer a senha em texto puro, avise que precisa converter.

### Comandos Disponíveis

| Comando Hermes | Ação | CLI |
|---|---|---|
| `terminal("matera me")` | Dados do usuário logado | me |
| `terminal("matera balance")` | Saldos da conta | balance |
| `terminal("matera statement")` | Extrato bancário | statement |
| `terminal("matera transactions --limit 10")` | Últimas transações | transactions |
| `terminal("matera payment --amount 150.00 --description 'Cliente'")` | Criar pagamento | payment |
| `terminal("matera banks")` | Listar bancos disponíveis | banks |
| `terminal("matera draft --value 200.00")` | Solicitar saque | draft |
| `terminal("matera wallet")` | Ver carteira de cartões | wallet |
| `terminal("matera timeline")` | Timeline da conta | timeline |
| `terminal("matera coupons")` | Cupons disponíveis | coupons |
| `terminal("matera permissions")` | Permissões do usuário | permissions |
| `terminal("matera client-info")` | Dados completos do cliente | client-info |

### Config

```python
# Definir account_id padrão
terminal("matera config set --key account_id --value 12345")

# Ver config atual
terminal("matera config list")
```

## Fluxos Comuns

### Verificar Saldo

```python
terminal("matera balance")
```

### Consultar Extrato Recente

```python
terminal("matera statement")
terminal("matera transactions --limit 5")
```

### Fazer um Pagamento

```python
terminal("matera payment --amount 250.00 --description 'Serviço de consultoria'")
```

### Listar Transações e Detalhar

```python
result = terminal("matera transactions --limit 20")
# Analisar o JSON de retorno
```

## Observações

- A API base é `https://api_mp.matera.com.br`
- Autenticação: Bearer token via header `Authorization`
- Endpoint de pagamento requer header `S-transaction` (gerado automaticamente pelo CLI)
- O CLI gerencia cache de token automaticamente em `~/.hermes2/scripts/matera-cli/`
- A API Matera é B2B — requer contrato/parceira para acesso

## Workflow para Novos Projetos CLI Financeiros Brasil

Siga este fluxo padronizado para criar novos projetos na categoria (ex: bb-cli, btg-cli, open-finance-br-cli):

1. **Mapeie o projeto** com `llm-project-mapper` para gerar AGENTS.md, CLAUDE.md, INIT.md e estrutura de agentes.
2. **Crie a skill** seguindo esta estrutura de SKILL.md (pré-requisitos, uso com Hermes, comandos, configuração, observações).
3. **Atualize o README** com seção de onboarding para agentes (🤖 Onboarding para Agentes) indicando status `ralph_ready: true`.
4. **Inicialize o Git**: `cd <projeto> && git init && git add . && git commit -m "Initial commit"`
5. **Configure remote preferencialmente via HTTPS** para evitar erros de chave SSH:
   `git remote add origin https://github.com/wesleysimplicio/<repo>.git`
6. **Crie o repositório no GitHub** via `gh` CLI (já autenticado):
   `gh repo create wesleysimplicio/<repo> --public --source=. --push`
7. **Push para o origin**: `git push -u origin main` (ou `master` se o branch padrão for outro)

## Pitfalls

- **Erro de SSH `Permission denied (publickey)`**: Se o push falhar por chave SSH não configurada, troque o remote para HTTPS em tempo real:
  `git remote set-url origin https://github.com/wesleysimplicio/<repo>.git` e repita o push.
- **Claude Code CLI**: Pode retornar 401 se a autenticação não estiver ativa; use `gh` CLI diretamente como fallback confiável.
- **Codex CLI**: O flag `-p` é exclusivo para perfis de configuração (ex: `-p mass`), não para entrada piped. Tentar `echo "prompt" | codex` falhará com erro de terminal. Se o Codex não estiver configurado, use `gh` CLI.
- **Skills no ~/.hermes2/**: Ao commitar skills localmente, crie um `.gitignore` primeiro para evitar expor `.env`, tokens ou dados de sessão.