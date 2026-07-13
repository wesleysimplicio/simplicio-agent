# Batch Command Reference — 18 Comandos em 1

## Meta: `simplicio status --all` (Rust nativo)

**Status:** Código criado em `src/status_command.rs`, registrado no `main.rs`. Aguardando build release compilar.

## Até lá: Script Bash (PR #2845, já mergeado)

```bash
bash scripts/simplicio-batch-command.sh <grupo> [--json]
```

### Grupos

| Grupo | Comandos | O que mostra |
|---|---|---|
| `diagnostics` | doctor + runtime-map + memory-db | Saúde do sistema |
| `connectors` | browser + computer-use + cron | Conectores ativos |
| `savings` | report + whoami + prove | Economia de tokens |
| `updates` | update-status + update-check + license | Versão e licença |
| `whoami` | auth + license + version | Identidade |
| `agents` | agents-status + governor-simulate + parallelism | Pool de agentes |

### Redução: 18 comandos → 6 grupos → 1 comando `--all` (em breve)

## Roadmap para Rust Nativo

- [x] `src/status_command.rs` criado (71 linhas)
- [x] Registrado no `main.rs`
- [x] Build release em andamento
- [ ] `simplicio status --all` — unifica os 6 grupos
- [ ] `simplicio status diagnostics` — grupo específico
- [ ] Execução paralela com Tokio (cada comando = tokio task)
- [ ] Output compactado com TOON (`--for-llm markdown`)
