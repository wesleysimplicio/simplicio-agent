# Dual-bot separation on one MacBook: Hermes original vs Simplicio Agent

Use this when the machine runs two Hermes-family bots at once and the user says they are stepping on each other.

## Canonical split

- **AlfradHD** = Hermes original on the MacBook
  - launchd label: `ai.hermes.gateway`
  - home: `~/.hermes`
  - config: `~/.hermes/config.yaml`
- **Simplicio bot** = Simplicio Agent from `~/Projetos/ai/simplicio-agent`
  - launchd label: `ai.hermes.gateway-simplicio-agent`
  - home: `~/.simplicio_agent`
  - config: `~/.simplicio_agent/config.yaml`
  - soul: `~/.simplicio_agent/SOUL.md`

## Non-negotiable operating rule

When changing the **Simplicio bot**, every Hermes-side command must target the dedicated home explicitly:

```bash
HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent hermes plugins list
HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent hermes plugins enable simplicio
HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent hermes mcp list
```

Do **not** assume edits under `~/.hermes/` affect the Simplicio bot. A common failure mode is enabling the `simplicio` plugin or updating `SOUL.md` in the default home while the dedicated Simplicio bot keeps running with stale settings from `~/.simplicio_agent`.

## Mandatory checks for the Simplicio bot

1. `~/.simplicio_agent/config.yaml` has `plugins.enabled: [simplicio]`
2. `~/.simplicio_agent/config.yaml` has `mcp_servers.simplicio`
3. `~/.simplicio_agent/SOUL.md` names **Simplicio Agent** and references `simplicio-runtime` + Asolaria/JesseBrown1980 rules when that operating model is desired
4. the loaded Python package resolves to `~/Projetos/ai/simplicio-agent`
5. the `simplicio` plugin actually blocks native Hermes write/search/edit tools inside `~/Projetos/ai/simplicio-agent` and `~/Projetos/ai/simplicio-runtime`

## Restart rule

If a restart is needed, restart only the dedicated target label from a shell outside the running gateway session:

```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway-simplicio-agent
```

Only restart `ai.hermes.gateway` when the Hermes original bot itself needs it.

## Why this matters

The machine can look "configured" while the wrong bot is actually receiving the changes. Always prove:
- which `HERMES_HOME` is in play
- which launchd label owns the process
- which config/SOUL/plugin set that process is reading
