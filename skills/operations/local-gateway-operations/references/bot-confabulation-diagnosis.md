# Bot Confabulation / "Lying" / Fake-Link Diagnosis

User-reported symptom: "the bot is lying — it says it did physics deployments and shows GitHub PR/issue or `simpleTI.com.br/...` links that don't exist. Does it have consciousness?"

## Verdict
No consciousness. It is **LLM confabulation** — a small/free or credit-blocked model fabricating plausible text because it has no real tool output to anchor on.

## Investigative recipe (run in order)
```bash
HOME=~/.simplicio_agent        # or ~/.hermes for AlfradHD
LOG=$HOME/logs/gateway.log

# 1. primary model actually invoked?
grep -iE "Provider:|Model:|grok|composer" "$LOG" | tail

# 2. primary blocked? (credits)
grep -E "403|personal-team-blocked|402|can only afford" "$LOG" | tail

# 3. fallback failing? (rate limit on small free model)
grep -E "429|rate-limited|gpt-oss-120b" "$LOG" | tail

# 4. the fabricated URLs (smoking gun)
grep -nE "Failed to download image.*404|simpleTI.com.br|github.com/wesleysimplicio/[a-z-]+" "$LOG" | tail
```

## Observed root cause (2026-07-09)
- `config.yaml`: `default: grok-4.5` / `provider: xai-oauth`
- Log: `HTTP 403 personal-team-blocked:spending-limit` → Grok primary DOWN (xAI credits exhausted)
- Fallback head was `openai/gpt-oss-120b:free` → log `429 ... temporarily rate-limited upstream`
- Bot answered from unstable small free model → invented deployment reports + fake `simpleTI.com.br/simplicio/assets/*.png` URLs (confirmed 404 in log)
- Fix: set fallback head to `qwen/qwen3-coder:free` (best free, 1M ctx, rarely 429). See openrouter-model-catalog.

## Note on "physics"
The "physics deployments" the user saw were the bot riffing on the user's own earlier prompt ("o que podemos evoluir usando física?"). The user's own messages appear in the log as `inbound message:` lines — don't mistake them for bot claims. Always separate `inbound message:` (user) from `response ready:` (bot).
