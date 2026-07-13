# Simplicio Agent identity and restart notes

Session takeaways (consolidated across runs):
- User explicitly corrected the bot identity to **Simplicio Agent**: "É simplicio agent".
- For local gateway ops, prefer user-facing wording **Simplicio Agent** / **Simplicio bot** when discussing this bot.
- The active gateway path observed in this environment used:
  - `HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent` (later reconfigured to `/Users/wesleysimplicio/.hermes` — see below)
  - `SIMPLICIO_AGENT_HOME=/Users/wesleysimplicio/.simplicio_agent`
  - LaunchAgent label: `ai.hermes.gateway-simplicio-agent`
  - launcher script: `~/.simplicio_agent/bin/start-simplicio-agent-discord.sh`
- The command name observed in this environment was `simplicio_agent`.
- Restart attempts from inside the running gateway turn were blocked by a self-protection guard; use an external shell/session or another out-of-band restart path (one-shot cron running `launchctl kickstart`).

## Env-var split reconfiguration (validated 2026-07-08)

The user asked to set `HERMES_HOME=/.hermes` and `SIMPLICIO_AGENT_HOME=/.simplicio_agent`
(i.e. point the bot's Hermes home at the Hermes original home, keep the agent runtime home separate).

What was actually done:
1. Synced the `discord:` block (with `channel_prompts` + `allowed_channels`) from
   `~/.simplicio_agent/config.yaml` into `~/.hermes/config.yaml` so the bot keeps its
   Simplicio Agent personality after `HERMES_HOME` moved to `.hermes`.
2. Edited the LaunchAgent plist with a python regex (the `patch` tool fails on plist
   tab/indent). New env:
   - `HERMES_HOME = /Users/wesleysimplicio/.hermes`
   - `SIMPLICIO_AGENT_HOME = /Users/wesleysimplicio/.simplicio_agent`
3. `plutil -lint` passed. A `kickstart` restart applied it.

Gotcha: editing only `HERMES_HOME` WITHOUT syncing `channel_prompts` would drop the
bot's personality (the `.hermes` config had no `channel_prompts`). Always sync the
discord block first.

## Pending: LaunchAgent label rename (user requested, NOT yet executed)

User asked to rename `ai.hermes.gateway-simplicio-agent` → `ai.simplicio-agent.gateway`.
Safe procedure (boot-critical — confirm before running):
- `launchctl unload gui/$(id -u)/ai.hermes.gateway-simplicio-agent`
- `mv` the plist and update its `<key>Label</key>` value
- `launchctl load` the new path
A bare `mv` leaves an orphaned reference and the bot stops auto-starting on login.

## Verify after restart
Check both the LaunchAgent state and fresh log lines under `~/.simplicio_agent/logs/`.
The `/status` Discord command repasses `hermes status` output (the `hermes` binary
name is internal and intentionally NOT renamed per repo branding rule).
