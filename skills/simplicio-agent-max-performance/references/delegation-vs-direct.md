# Delegation vs Direct Implementation — Pitfall Reference

## Regra: Implementar direto no terminal, delegar só pesquisa

**Aprendizado crítico (Jul 2026, 2x correção do usuário):**

Subagentes via `delegate_task` DESVIAM quando recebem goal de implementar código.
Em vez de escrever código, pesquisam GitHub por "alguém que já fez".

### Quando usar cada um

| Quer fazer | Use | NUNCA use |
|---|---|---|
| Implementar feature | terminal + `simplicio edit` | `delegate_task` |
| Pesquisar conceitos | `delegate_task` | terminal (lento) |
| Rodar testes | `cargo test` direto | delegate_task |
| Estudar raciocínio | terminal (`claude --print`) | delegate_task (auth/model falha) |
| Verificar existência | `simplicio search` / `grep` | delegate_task |

### Por que subagentes desviam

1. Subagente recebe: "Implementar X no arquivo Y.rs"
2. Subagente decide: "Vou ver se alguém já implementou isso" 
3. Roda `gh search repos 'X'` — 5min perdidos
4. Encontra repos similares mas não implementa nada
5. Entrega: "Achei Z repos similares" — zero linhas de código

### Exemplo real desta sessão

```
Delegado: "Implementar pool dinâmico de agents (Little's Law)"
Resultado: Buscou "cosign chain" no GitHub. Zero implementação.

Delegado: "Implementar decision cache (Landauer)"
Resultado: Buscou "Karpathy memory consolidation". Zero implementação.
```

### Solução

Para implementar: `terminal()` + `simplicio edit` — feito na raça, 5-10min.
Para pesquisar: `delegate_task` com goal explícito de "pesquisar, não implementar".
