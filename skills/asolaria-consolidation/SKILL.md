---
name: asolaria-consolidation
description: "Karpathy-style consolidation: compila observacoes brutas em paginas markdown no fim da sessao. Reduz memoria crua em conhecimento."
---

# Asolaria Consolidation

Use no final de cada sessao para transformar observacoes brutas em conhecimento durável.

## Fluxo
1. Colete todas as observacoes da sessao atual
2. Peca ao LLM para compilar em paginas markdown concisas
3. Salve em `~/.simplicio/wiki/<projeto>/<data>-<topico>.md`
4. Atualize o `INDEX.md` do wiki com o novo link

## Prompt de consolidacao
```
Compile as observacoes abaixo em paginas markdown concisas.
Cada pagina deve ter: titulo, descricao, decisoes tecnicas, e proximos passos.
Agrupe por topico. Ignore ruido.

<observations>
{{observations}}
</observations>
```

## Gatilho
Automatico via cron ou ao final de `simplicio run --evidence`.
