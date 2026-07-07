---
name: asolaria-consolidation
description: "Karpathy-style consolidation: compila observações brutas em páginas markdown no fim da sessão e registra lessons duráveis."
---

# Asolaria Consolidation

Use no final de uma sessão para transformar notas soltas em conhecimento reutilizável.

## Fluxo
1. Colete as observações da sessão atual.
2. Agrupe por tópico e descarte ruído.
3. Escreva páginas markdown curtas em `~/.simplicio/wiki/<projeto>/<data>-<topico>.md`.
4. Atualize o `INDEX.md` do wiki com o novo link.
5. Registre os aprendizados duráveis em `simplicio-learn` ou memória persistente quando houver correção, precedente ou preferência estável.

## Prompt de consolidação
```
Compile as observações abaixo em páginas markdown concisas.
Cada página deve ter: título, descrição, decisões técnicas, blockers, e próximos passos.
Agrupe por tópico. Ignore ruído e não copie transcript literal.

<observations>
{{observations}}
</observations>
```

## O que salvar
- decisões técnicas
- tradeoffs que voltam
- bugs que tiveram correção durável
- preferências estáveis do usuário

## O que não salvar
- transcript cru
- progresso temporário
- notas que mudam no próximo turno

## Gatilho
Automático via cron, no fim de `simplicio run --evidence`, ou quando o usuário pedir retrospectiva/recordação.
