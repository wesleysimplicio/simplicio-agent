# Discord 401 from `simplicio` binary while `curl` with the same token returns 200

Root-caused 2026-07-10 on this host (`~/.simplicio_agent` bot, binary
`~/.local/bin/simplicio` built 2026-07-09).

## Symptom

```
$ simplicio gateway listen discord
simplicio: discord auth failed: {"message": "401: Unauthorized", "code": 0}
```
But:
```
$ TOK=$(grep '^DISCORD_BOT_TOKEN=' ~/.simplicio_agent/.env | cut -d= -f2-)
$ curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bot $TOK" https://discord.com/api/v10/users/@me
200
```
The token is valid. So why does the binary 401?

## Two independent causes

### 1. The binary does NOT auto-load `.env`
Env vars must be exported into the binary's environment. A bare launch
(`simplicio gateway listen discord`) sees no `DISCORD_BOT_TOKEN` unless the
launcher exports it. Safe launcher (python; also avoids `source` breaking on
unquoted spaces in `.env`):

```python
import os
envs = {}
for line in open('/Users/wesleysimplicio/.simplicio_agent/.env').read().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    envs[k.strip()] = v.strip()
for k in ['DISCORD_BOT_TOKEN', 'SIMPLICIO_DISCORD_TOKEN',
          'DISCORD_APP_ID', 'SIMPLICIO_DISCORD_APP_ID',
          'DISCORD_PUBLIC_KEY', 'DISCORD_ALLOWED_USERS',
          'SIMPLICIO_DISCORD_CHANNEL_ID', 'DISCORD_CHANNEL_ID',
          'OPENROUTER_API_KEY']:
    if k in envs:
        os.environ[k] = envs[k]
os.environ['SIMPLICIO_AGENT_HOME'] = '/Users/wesleysimplicio/.simplicio_agent'
os.execv('/Users/wesleysimplicio/.local/bin/simplicio',
         ['simplicio', 'gateway', 'listen', 'discord'])
```

### 2. Subcommands read DIFFERENT env-var names
- `simplicio discord status` → `discord_config()` in
  `src/main_parts/chunk_18.rs:514` reads `SIMPLICIO_DISCORD_BOT_TOKEN`
  then `DISCORD_BOT_TOKEN` (and needs `SIMPLICIO_DISCORD_CHANNEL_ID` /
  `DISCORD_CHANNEL_ID` or it reports "not configured").
- `simplicio gateway listen discord` → `DiscordGateway` in
  `src/gateway/platforms/discord.rs` reads `SIMPLICIO_DISCORD_TOKEN`
  (channel: `SIMPLICIO_DISCORD_CHANNEL_ID`, app id: `SIMPLICIO_DISCORD_APP_ID`).
  `connect()` calls `verify_token()` (line 233) which returns
  `discord auth failed: {body}` on a 401.

If `.env` only defines `DISCORD_BOT_TOKEN` (as this host's did), `gateway
listen` does NOT pick it up and may authenticate with a stale/empty token → 401.

## Fix
Set BOTH names in the launcher / `.env`:
```
DISCORD_BOT_TOKEN=...        # for `simplicio discord status`
SIMPLICIO_DISCORD_TOKEN=...  # for `simplicio gateway listen discord`
SIMPLICIO_DISCORD_CHANNEL_ID=<channel_id>
```
(they can hold the same value). Then launch with the python loader above.

## Verify
- `simplicio discord status` → no longer "not configured".
- `simplicio gateway listen discord` → log shows Discord connected, no 401.
- Independent token check: `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bot $TOK" https://discord.com/api/v10/users/@me` must be `200`.

## SECURITY NOTE
When inspecting/masking the token, never interpolate the value into output.
Use `print(f'DISCORD_BOT_TOKEN=[REDACTED len={len(v)}]')` from python, not a
`sed` substitution that captures the value group. A bad `sed` mask leaked the
live token into chat this session — rotate the bot token after any such leak.
