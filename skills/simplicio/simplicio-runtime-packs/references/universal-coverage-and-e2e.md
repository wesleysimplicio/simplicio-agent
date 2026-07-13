# Universal Command Coverage + End-to-End Flow

> Documentos canônicos criados em 03/07/2026 na sessão de evolução massiva do runtime.

## UNIVERSAL_COMMAND_MATRIX.md

**Path:** `docs/UNIVERSAL_COMMAND_MATRIX.md` (478 linhas, 14.2 KB)
**Cobertura:** 14 ferramentas (Claude Code · Codex · Hermes · VSCode · Cursor · OpenCode ·
Kiro · Antigravity · Gemini · Aider · OpenClaw · git · bash · PowerShell)

Cada comando de cada ferramenta mapeado para simplicio-runtime via:
- ✅ MCP (10 tools via `simplicio serve --mcp --stdio`)
- ✅ CLI (66 comandos via `simplicio <comando>`)
- ✅ loop (simplicio-loop como motor obrigatório)
- ✅ dev-cli (`simplicio dev-cli`)
- ✅ edit (`simplicio edit --plan`)
- ✅ sprint (`simplicio sprint`)
- ✅ shell (`simplicio shell --`)
- ✅ validate (`simplicio validate`)
- ⚠️ parcial (contrato/UX diferente)
- ❌ gap (sem cobertura direta — vira feature)

## END_TO_END_FLOW.md + e2e-verify.sh

**Docs:** `docs/END_TO_END_FLOW.md` (documentação do framework)
**Script:** `scripts/e2e-verify.sh` (executável, 90 linhas)

### Pipelines suportados

| Pipeline | Comando | O que verifica |
|----------|---------|----------------|
| full-stack | `simplicio flow verify --pipeline full-stack` | Cadeia completa: front→back→db→ext→workers |
| frontend | `simplicio flow verify --pipeline frontend --url <url>` | build → lint → test → e2e (Playwright) |
| backend | `simplicio flow verify --pipeline backend --api <endpoint>` | build → lint → test → integração |
| database | `simplicio flow verify --pipeline database` | migration → seed → query → rollback |
| workers | `simplicio flow verify --pipeline workers` | queue → process → result → retry → dead-letter |

### Gatilhos automáticos

- Pré-commit (via `hooks/pre-commit`)
- Pré-PR (via GitHub Actions)
- `simplicio run` (toda execução)
- `simplicio validate --e2e`
- Cron semanal (full-stack)

### Evidência

Cada pipeline escreve receipt em `.simplicio/e2e/<pipeline>/<timestamp>.json`:
```json
{"pipeline":"full-stack","timestamp":"20260703_170500","status":"passed","duration_ms":45200,"stages":["build","lint","test","e2e","integration","db","workers"]}
```

## simplicio-loop-compliance.md (invertido)

**Path:** `docs/simplicio-loop-compliance.md` (203 linhas, 9 KB)

**Inversão de dependência:**
- ANTES: simplicio-loop era super-plugin OPCIONAL que podia usar runtime
- AGORA: simplicio-loop é parte INTEGRANTE do simplicio-runtime (MANDATÓRIO)
- Toda execução (run, edit, validate, MCP) passa pelo loop de convergência

## setup-agents.sh (cobertura universal)

**Path:** `scripts/setup-agents.sh`

Registra MCP em TODOS os 11 runtimes:
Claude Code · Codex CLI · Hermes Agent · VS Code/Copilot · Cursor IDE · OpenCode CLI ·
Kiro CLI · Antigravity CLI · Gemini CLI · Aider CLI · OpenClaw · Terminal/Bash · PowerShell

## viral-product-strategist

**Path:** `skills/marketing-vendas/viral-product-strategist/SKILL.md` (1.836 linhas)

Skill de 32 princípios de produtos virais do sergiobanhos/skills. Instalada no runtime.
