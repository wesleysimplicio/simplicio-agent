---
name: portfolio-observability
description: Use when monitoring or troubleshooting the personal portfolio observability stack (GH Actions, Paperclip, Discord bot, Hermes gateway, prod health). Covers the launchd-driven Portfolio Watch, alert routing to the SENTINEL Discord channel, and the state-diff alerting model.
version: 1.0.0
author: Wesley Simplicio
license: MIT
metadata:
  hermes:
    tags: [observability, monitoring, discord, github-actions, hermes, portfolio, alerts]
    related_skills: [executive-operations-lenses]
---

# Portfolio Observability

## Overview

Centralized self-monitoring for Wesley's portfolio. Single shell script polled by `launchd` every 5 minutes; alerts routed to Discord channel `SENTINEL` (`1478147252823527685`) using the existing `DISCORD_BOT_TOKEN` from `~/.hermes/.env`.

Alerts fire only on **state change** (OK→FAIL or FAIL→OK), avoiding noise. A daily heartbeat at 09:00 BRT confirms the watcher itself is alive even when nothing fails.

## Components

| Component | Path |
|---|---|
| Watcher script | `~/.hermes/scripts/hermes_portfolio_watch.sh` |
| LaunchAgent | `~/Library/LaunchAgents/ai.hermes.portfolio-watch.plist` |
| State file | `~/.hermes/tmp/portfolio_watch_state.json` |
| Heartbeat marker | `~/.hermes/tmp/portfolio_watch_heartbeat` |
| Run log | `~/.hermes/logs/portfolio-watch.log` |
| Launchd stdout/err | `~/.hermes/logs/portfolio-watch.launchd*.log` |

## Targets monitored

1. **GH Actions** — `gh run list --limit 1` per repo:
   - `wesleysimplicio/saas-consultoria-imagem`
   - `wesleysimplicio/sistema-sindico`
   - `wesleysimplicio/AppDental`
2. **Paperclip** — `curl http://127.0.0.1:3100/api/companies` (200 = ok).
3. **Discord bot** — `pgrep -f "hermes_cli.main gateway"` (Hermes gateway hosts the bot).
4. **Hermes self** — same gateway process check.
5. **Prod health** (opcional) — habilitar exportando `PROD_HEALTH_URL=<url>` no `.env` ou no plist `EnvironmentVariables`. Sem URL = check `skip|disabled` (sem alerta).

## State model

Each tick builds a JSON state and compares to previous. Per-target value format:
```
"<status>|<label>|<detail>"
```
- `status ∈ {ok, fail, running, none, skip}`
- Diff fires alert only for `ok ⇄ fail` transitions. `running` and `skip` are quiet.
- First run after deletion of state file is silent (no spurious alerts).

## Alert format

Fail:
```
🛰️ Portfolio Watch — 2026-05-06 21:25 BRT
❌ GH Actions falhou — `wesleysimplicio/saas-consultoria-imagem` · Deploy · failure
❌ paperclip caiu: 502
```

Recovery:
```
🛰️ Portfolio Watch — 2026-05-06 21:30 BRT
✅ GH Actions verde — `wesleysimplicio/saas-consultoria-imagem` · Deploy
```

Heartbeat (09:00 BRT diário):
```
✅ Heartbeat 2026-05-06 — Portfolio Watch operacional.
• Repos GH: ok:3
• Paperclip: ok|200
• Prod: skip|disabled
• Bot: ok|gateway
• Hermes: ok|running
```

## Operations

### Manual run
```bash
bash ~/.hermes/scripts/hermes_portfolio_watch.sh
```

### Reset state (forces silent first-run baseline)
```bash
rm -f ~/.hermes/tmp/portfolio_watch_state.json
```

### Reload launchd
```bash
launchctl unload ~/Library/LaunchAgents/ai.hermes.portfolio-watch.plist
launchctl load -w ~/Library/LaunchAgents/ai.hermes.portfolio-watch.plist
launchctl list | grep portfolio-watch
```

### Tail live
```bash
tail -f ~/.hermes/logs/portfolio-watch.log
```

### Force test alert
Stop Paperclip (or any monitored service) and wait ≤5min, then restart it. Two messages expected: ❌ caiu, ✅ recuperou.

## Adding a new check

1. Adicione função `check_<name>` no script retornando `<status>|<label>`.
2. Inclua a chave em `build_state` (`--arg <name> "$(check_<name>)"`).
3. Adicione `<name>` ao loop de comparação (`for k in paperclip prod bot hermes <name>`).
4. Reset state file e recarregue o launchd agent.

## Adding a new repo

Editar array `REPOS=( ... )` no script. Sem outras mudanças — o loop GH itera tudo.

## Known limits

- `gh run list` requer `gh auth status ✓` no shell do launchd. Token vive em keyring (já configurado).
- `pgrep` da gateway pode dar falso negativo durante restart curto; intervalo 5min absorve.
- Discord rate limit: ~5 msg/5s/canal. Heartbeat + alertas comuns ficam abaixo.
- Sem suporte a SSH HostGator no MVP — adicionar `check_hostgator_logs` se credenciais forem expostas via env.

## Verification checklist

- [ ] `launchctl list | grep portfolio-watch` retorna PID > 0
- [ ] `~/.hermes/tmp/portfolio_watch_state.json` existe e tem JSON válido
- [ ] Mensagem de teste chegou em SENTINEL (`1478147252823527685`)
- [ ] Logs em `~/.hermes/logs/portfolio-watch.log` mostram `tick ok` a cada 5min
