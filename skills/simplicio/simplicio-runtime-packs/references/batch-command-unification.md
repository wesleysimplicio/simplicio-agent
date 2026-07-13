# Batch Command Unification (18 → 6 comandos)

Unifica 3 comandos similares em 1. Reduz sobrecarga cognitiva em 67%.

## Grupos

| Grupo | 3 comandos antigos | 1 comando novo |
|---|---|---|
| diagnostics | doctor + runtime-map + memory-db | `simplicio status diagnostics` |
| connectors | browser + computer-use + cron | `simplicio status connectors` |
| savings | report + whoami + prove | `simplicio status savings` |
| updates | update-status + update-check + license | `simplicio status updates` |
| identity | auth + license + version | `simplicio status identity` |
| agents | agents-status + governor + parallelism | `simplicio status agents` |
| **all** | **todos acima** | **`simplicio status --all`** |

## Uso via script (enquanto Rust nativo não compila)

```bash
bash scripts/simplicio-batch-command.sh <grupo> [--json]

# Exemplos
bash scripts/simplicio-batch-command.sh status --json    # 3 diagnosticos
bash scripts/simplicio-batch-command.sh connectors        # 3 conectores
bash scripts/simplicio-batch-command.sh all --json        # TUDO (18 comandos)
```

## Comando nativo Rust (em compilação)

`src/status_command.rs` — módulo Rust que será o `simplicio status --all` nativo.
Usa `std::process::Command` para rodar os 18 sub-comandos em paralelo e agregar.
Schema: `simplicio.status/v1`.

## PR de referência

PR #2845 — `feat: batch command — unify 3 commands into 1`
