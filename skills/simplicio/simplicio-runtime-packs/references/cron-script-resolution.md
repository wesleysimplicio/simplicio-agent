# Cron Job Script Resolution — Armadilhas e Padrões

## Resolution Rules (no_agent mode)

Quando um cron job tem `no_agent=true` e `script` definido, o scheduler:

1. **Resolve paths relativos** sob `~/.simplicio_agent/scripts/`
   - `script: "clean-mcp.sh"` → executa `~/.simplicio_agent/scripts/clean-mcp.sh`
   - `script: "scripts/clean-mcp.sh"` → executa `~/.simplicio_agent/scripts/scripts/clean-mcp.sh` **⚠️ path duplicado!**

2. **NÃO separa argumentos do nome do arquivo**
   - `script: "clean-mcp.sh --cron"` → procura ARQUIVO chamado `clean-mcp.sh --cron` — **não funciona**
   - O campo `script` é tratado como path literal, não como comando + args

3. **Regra:** o valor do campo `script` é o path relativo ao diretório de scripts. Argumentos NÃO cabem neste campo.

## Soluções

### Para scripts que precisam de argumentos

**Opção A: Default no script** (recomendado)
```bash
#!/bin/bash
MODE="${1:---cron}"     # --cron como default
# ... lógica do script ...
```
No cronjob: `script: "meu-script.sh"` (sem argumentos)

**Opção B: Wrapper script**
```bash
#!/bin/bash
exec ~/.simplicio_agent/scripts/meu-script.sh --cron "$@"
```
Salvar como `meu-script-wrapper.sh` no mesmo diretório.

### Para scripts que não são encontrados

Diagnóstico:
```bash
# Verificar se o path existe
ls -la ~/.simplicio_agent/scripts/<script-name>
# O script DEVE estar neste diretório para resolução relativa

# Alternativa: path absoluto
script: "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/scripts/clean-mcp.sh"
```

## clean-mcp.sh — Script de Referência

Localização: `~/.simplicio_agent/scripts/clean-mcp.sh`
Cronjob: `clean-mcp-orphans` (job_id: 99320fa9c848)

O script:
- Mata processos MCP órfãos (simplicio serve --mcp sem pai vivo)
- Remove sockets MCP >1h sem uso
- Limpa symlinks quebrados
- Mata zumbis (processos estado Z)
- Modo `--cron` (default): silencioso se nada foi limpo
- Modo `--verbose`: reporta contagem sempre

Cronjob config:
```json
{
  "name": "clean-mcp-orphans",
  "script": "clean-mcp.sh",       // sem prefixo scripts/, sem argumentos
  "no_agent": true,
  "schedule": "every 60m",
  "workdir": "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime"
}
```

## Histórico de Correções

**05/07/2026 — Path duplicado:** O cronjob original tinha `script: "scripts/clean-mcp.sh --cron"` que resolveu para `~/.simplicio_agent/scripts/scripts/clean-mcp.sh --cron` — path duplicado + argumento tratado como filename. Corrigido para `script: "clean-mcp.sh"`.
