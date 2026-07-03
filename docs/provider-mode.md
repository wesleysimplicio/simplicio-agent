# Provider-mode — 3 modos de operação

Este documento descreve os três modos de operação do Simplicio Agent,
definidos pelo contrato `ADR-0002` (ver `docs/architecture/ADR-0002-provider-mode-contract.md`
para detalhes técnicos completos).

## Os três modos

O Simplicio Agent opera com o **mesmo binário** em três papéis distintos,
diferenciados por como o provedor de LLM é resolvido:

### 1. Standalone (autônomo)

| Campo | Valor |
|-------|-------|
| **Invocação** | CLI, gateway (não-MCP) |
| **LLM calls internas?** | Sim (loop completo de raciocínio + ação) |
| **Provedor usado** | Próprio (`~/.simplicio/`) |
| **Atribuição de custo** | O operador do agente paga |

**Uso típico:** Você abre o terminal e roda `simplicio` diretamente — o agente
age como um assistente autônomo completo, raciocinando e executando ações.

### 2. Tool (ferramenta)

| Campo | Valor |
|-------|-------|
| **Invocação** | MCP sem `provider_ref` |
| **LLM calls internas?** | **Não** — determinismo por contrato |
| **Provedor usado** | Frio (não usado) |
| **Atribuição de custo** | O operador paga (operações determinísticas são baratas) |

**Uso típico:** Um LLM externo (Claude Code, ChatGPT, etc.) chama o Simplicio
via MCP para uma operação discreta e determinística: mapear um repositório,
editar um arquivo, executar um teste. O agente NÃO faz chamadas de LLM
próprias — age como uma ferramenta pura.

### 3. Delegated (delegado)

| Campo | Valor |
|-------|-------|
| **Invocação** | MCP com `provider_ref` explícito |
| **LLM calls internas?** | Sim (loop completo) |
| **Provedor usado** | Do caller (se autorizado pelo Action Gate) |
| **Atribuição de custo** | O caller paga (se `provider_ref` passado e aprovado) |

**Uso típico:** Um LLM externo delega uma tarefa completa para o Simplicio,
passando suas próprias credenciais de provedor. O agente executa o loop
autônomo usando o provedor do caller, que arca com os custos.

## Regra de resolução (único ponto de decisão)

```python
if not origin.is_mcp:
    return ProviderMode.STANDALONE
if origin.has_provider_ref:
    return ProviderMode.DELEGATED
return ProviderMode.TOOL
```

## Segurança de credenciais (não negociável)

1. A credencial do caller entra apenas por `provider_ref` explícito na requisição MCP.
2. Passa pelo **Action Gate** (`classify`) antes de qualquer uso.
3. Usada **apenas naquela sessão** — nunca persistida em disco/config.
4. **Redatada** de todos os logs/evidências.
5. Sem `provider_ref` explícito → modo delegado usa ladder local, ponto final.

## Ver também

- `docs/architecture/ADR-0002-provider-mode-contract.md` — especificação técnica completa
- `agent/telemetry/mcp_session.py` — telemetria de sessão MCP (issue #65)
- `agent/provider_mode.py` — implementação da resolução
