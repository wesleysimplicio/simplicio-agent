# Simplicio Discord Troubleshooting

## Session 2026-06-12 — .env path + expired token

### Symptom
Discord bot não respondia. Logs mostravam `ERROR: No DISCORD_BOT_TOKEN or SIMPLICIO_DISCORD_TOKEN set`.

### Root cause 1 — .env path mismatch
O launchd service `ai.simplicio.discord` executa `discord-daemon.sh start`, que
carrega env vars de `~/.simplicio/.env` via:

```bash
load_env() {
  if [ -f "${SIMPLICIO_HOME}/.env" ]; then
    set -a
    source "${SIMPLICIO_HOME}/.env"
    set +a
  fi
}
```

Mas o arquivo `.env` real está em `/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/.env`.
`~/.simplicio/.env` não existia.

**Fix:**
```bash
ln -sf /Users/wesleysimplicio/Projetos/ai/simplicio-runtime/.env ~/.simplicio/.env
```

### Root cause 2 — Token expirado
Depois de resolver o path, o log passou a mostrar `Invalid Discord token`.
Confirmação via curl: HTTP 401.

```bash
TOKEN=*** -o 'MTUxMz[^ ]*' /Users/wesleysimplicio/Projetos/ai/simplicio-runtime/.env | head -1)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bot $TOKEN" \
  https://discord.com/api/v10/users/@me
# → 401
```

**Fix:** Resetar token no Discord Developer Portal → Applications → Simplicio
→ Bot → Reset Token. Atualizar `.env`.

### Launchd state machine
O serviço estava em `state = spawn scheduled` — launchd tentava reiniciar a
cada ~8 segundos, mas o script morria imediatamente porque o .env não era
encontrado. O gateway guardian (`ai.simplicio.gateway`) estava em restart loop
com `LastExitStatus = 1`.

**Para parar o loop:**
```bash
launchctl bootout gui/$(id -u)/ai.simplicio.gateway
```

**Para reiniciar limpo:**
```bash
launchctl bootout gui/$(id -u)/ai.simplicio.discord
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.simplicio.discord.plist
```

### Arquivos relevantes
| Caminho | Função |
|---------|--------|
| `~/Library/LaunchAgents/ai.simplicio.discord.plist` | Launchd plist do adapter Python |
| `~/Library/LaunchAgents/ai.simplicio.gateway.plist` | Launchd plist do gateway nativo |
| `~/.simplicio/logs/discord-daemon.log` | Log do script daemon |
| `~/.simplicio/logs/discord.log` | stdout do Python adapter |
| `~/.simplicio/logs/discord.error.log` | stderr do Python adapter |
| `~/.simplicio/logs/gateway.error.log` | stderr do gateway nativo |
| `~/.simplicio/logs/guardian.log` | Log do gateway guardian |
| `~/.simplicio/discord_state.json` | Estado do adapter (PID, connected) |
| `~/.simplicio/gateway_state.json` | Estado do gateway (starting/running) |
| `~/.simplicio/discord.pid` | PID file do adapter Python |
| `/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/scripts/discord-daemon.sh` | Script launchd do adapter |
| `/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/scripts/discord-adapter.py` | Adapter Python propriamente dito |
