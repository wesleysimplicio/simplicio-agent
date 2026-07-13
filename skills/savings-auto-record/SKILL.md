---
name: savings-auto-record
description: Configura auto-recording de token savings no Simplicio para qualquer LLM
---

# Savings Auto-Record

Use esta skill quando quiser que LLMs registrem automaticamente seus token savings no Simplicio ledger.

## Comando Manual
```bash
~/.local/bin/simplicio savings record --spent ACTUAL --baseline BASELINE --source SOURCE --task "DESCRIPTION" --proof-kind estimated --json
```

## Uso no final de cada resposta
Adicione ao final de cada resposta de LLM que consumiu tokens:
```
Simplicio: ~X tokens · saved ~Y (Z%) vs baseline
```

## Script Automático
```bash
~/.hermes/scripts/savings-auto-record.sh TOKENS BASELINE "task description" source
```

## Dashboard
```bash
~/.local/bin/simplicio dashboard start --port 9119
# Abrir http://127.0.0.1:9119/
```

## Tray Icon (Desktop)
O Electron app em apps/simplicio-desktop/ tem tray icon com savings em tempo real.
Iniciar: `cd apps/simplicio-desktop && npm start`