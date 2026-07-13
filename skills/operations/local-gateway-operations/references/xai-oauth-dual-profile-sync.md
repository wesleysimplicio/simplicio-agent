# xAI OAuth (Grok) — sync between `.hermes` and `.simplicio_agent`

Session recipe (2026-07-08). Use when Simplicio Agent should use the **same SuperGrok / xAI OAuth** as Hermes original but `auth.json` in the bot home is stale or revoked.

## Symptom

- `~/.simplicio_agent/auth.json` has `providers.xai-oauth.last_auth_error` with `invalid_grant` / refresh revoked.
- `credential_pool.xai-oauth` is empty or missing `access_token`.
- `/model grok-composer-2.5-fast --provider xai-oauth` fails on Simplicio bot while Hermes original works.

## Fix (no secrets in chat)

1. Confirm Hermes home has working tokens (metadata only):

```bash
python3 - <<'PY'
import json
from pathlib import Path
for p in [Path.home()/'.hermes/auth.json', Path.home()/'.simplicio_agent/auth.json']:
    d=json.loads(p.read_text())
    x=d.get('providers',{}).get('xai-oauth',{})
    tok=x.get('tokens') or {}
    print(p.name, 'access', bool(tok.get('access_token')), 'refresh', bool(tok.get('refresh_token')),
          'err', bool(x.get('last_auth_error')))
PY
```

2. Sync provider block + pool from `.hermes` → `.simplicio_agent` (backup first):

```bash
python3 - <<'PY'
import json, shutil, time, copy
from pathlib import Path
src, dst = Path.home()/'.hermes/auth.json', Path.home()/'.simplicio_agent/auth.json'
backup = dst.with_name(f'auth.json.bak-grok-sync-{int(time.time())}')
shutil.copy2(dst, backup)
s, d = json.loads(src.read_text()), json.loads(dst.read_text())
xai = copy.deepcopy(s['providers']['xai-oauth'])
xai.pop('last_auth_error', None)
d.setdefault('providers', {})['xai-oauth'] = xai
pool = s.get('credential_pool', {}).get('xai-oauth')
if pool:
    d.setdefault('credential_pool', {})['xai-oauth'] = copy.deepcopy(pool)
dst.write_text(json.dumps(d, indent=2)+'\n', encoding='utf-8')
dst.chmod(0o600)
print('backup', backup)
PY
```

3. Restart Simplicio gateway (`/restart` or `launchctl kickstart` for `ai.hermes.gateway-simplicio-agent`).

4. Switch model in Discord: `/model grok-composer-2.5-fast --provider xai-oauth`

## Pitfalls

- **Do not paste tokens** in Discord, issues, or skill files — only copy via script.
- Syncing credentials **does not** change `model.default` in `config.yaml`; user may still be on OpenRouter until they `/model` switch.
- If Hermes home is also revoked, run `hermes auth add xai-oauth` (or `simplicio-agent auth add xai-oauth` with correct `HERMES_HOME`) — sync cannot fix an expired source.
- `patch` on `auth.json` is sensitive; prefer the script above or `hermes auth` CLI.