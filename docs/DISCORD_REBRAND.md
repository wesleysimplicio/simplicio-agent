# Discord Rebrand: Hermes → Simplicio Agent (user-facing)

**Commit:** `9600fbdeb` — `discord: rebrand user-facing Hermes strings to Simplicio Agent`
**Scope:** `plugins/platforms/discord/adapter.py` (Discord slash-command surface only)

## What changed

All **user-visible** strings in the Discord command surface were renamed from
`Hermes` to `Simplicio Agent`. The bot now presents itself to Discord users
exclusively as **Simplicio Agent**.

Affected command descriptions and user-facing messages:

| Surface | Before | After |
|---|---|---|
| `/reset` | Reset your Hermes session | Reset your Simplicio Agent session |
| `/status` | Show Hermes session status | Show Simplicio Agent session status |
| `/stop` | Stop the running Hermes agent | Stop the running Simplicio Agent |
| `/update` | Update Hermes Agent to the latest version | Update Simplicio Agent to the latest version |
| `/restart` | Gracefully restart the Hermes gateway | Gracefully restart the Simplicio Agent gateway |
| `/thread` | Create a new thread and start a Hermes session in it | Create a new thread and start a Simplicio Agent session in it |
| `/skill` | Run a Hermes skill | Run a Simplicio Agent skill |
| thread seed | Thread created by Hermes: **{name}** | Thread created by Simplicio Agent: **{name}** |
| handoff | Hermes session handoff / Hermes handoff: **{name}** | Simplicio Agent session handoff / Simplicio Agent handoff: **{name}** |
| default thread name | Hermes | Simplicio Agent |
| input prompt | ❓ Hermes needs your input | ❓ Simplicio Agent needs your input |
| thread error | ⚠️ Hermes could not create a Discord thread… | ⚠️ Simplicio Agent could not create a Discord thread… |
| home-channel hint | where Hermes delivers cron job results | where Simplicio Agent delivers cron job results |

## What was intentionally NOT changed

Per the repository branding rule ("internal code stays Hermes — never rename
variables, functions, config keys, module paths, or the `HERMES_*` env prefix"),
the following were left untouched:

- Python imports (`hermes_cli`, `hermes_constants`, `get_hermes_home`)
- Filesystem paths (`~/.hermes`, `hermes-gateway.exe`)
- Function / variable names, class names
- Internal docstrings and code comments
- The underlying binary name (`hermes`); only user-facing copy was rebranded

## Verification

- `python3 -c "import ast; ast.parse(adapter.py)"` → syntax OK
- `grep` for user-facing `Hermes` strings in the Discord adapter → 0 remaining
- Mirrored identically to `~/.simplicio_agent/plugins/platforms/discord/adapter.py`
  (the path the running bot loads) and the Simplicio_bot gateway was restarted
  to pick up the change.
