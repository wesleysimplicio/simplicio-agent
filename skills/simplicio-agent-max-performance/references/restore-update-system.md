# Restore & Update System

## Restore Points (Backup Diário)

| Item | Valor |
|---|---|
| Frequência | 03:00 todos os dias (cron `daily-backup-restore-point`) |
| Retenção | 7 dias girando |
| O que salva | Memória neural SQLite + config.yaml + SOUL.md + runtime-profile.json |
| Diretório | `~/.simplicio/backups/` |
| Nome | `neural-memory-YYYYMMDD.sqlite`, `agent-config-YYYYMMDD.yaml`, etc. |

### Como Restaurar

```bash
# Listar backups disponíveis
ls ~/.simplicio/backups/

# Restaurar memória neural de um dia específico
cp ~/.simplicio/backups/neural-memory-20260703.sqlite ~/.simplicio/memory/simplicio-memory.sqlite

# Restaurar config
cp ~/.simplicio/backups/agent-config-20260703.yaml ~/.simplicio_agent/config.yaml

# Após restore: verificar integridade
simplicio doctor --json
simplicio memory-db status --json
```

## Smart Update System

### Princípio: Runtime separado de dados do usuário

```
STATELESS (substituível)          STATEFUL (preservado)
├── binário ~/.local/bin/simplicio  ├── ~/.simplicio/memory/ (neural SQLite)
                                     ├── ~/.simplicio_agent/config.yaml
                                     ├── ~/.simplicio_agent/SOUL.md
                                     └── ~/.simplicio/profiles/runtime-profile.json
```

### Fluxo de Update

1. **Checagem**: cron `check-runtime-update` (segunda 10h) ou manual
2. **Backup**: backup automático de TODO o estado atual antes de qualquer mudança
3. **Compilação**: `cargo build --release --locked` (só o binário)
4. **Substituição**: copia `target/release/simplicio` → `~/.local/bin/simplicio`
5. **Verificação**: `simplicio version --json` — se falhar, rollback
6. **Rollback**: copia `backups/simplicio-rollback-<DATE>` de volta

### Script

```bash
bash ~/Projetos/ai/simplicio-runtime/scripts/simplicio-smart-update.sh
```

### Cuidados

- Áudio: sempre texto + MEDIA tag. Se MEDIA falhar, copiar pra Desktop.
- Update nunca mexe em: memória neural, perfil do usuário, SOUL.md, skills, config.yaml
- Se o update quebrar algo: restore point + rollback do binário anterior
