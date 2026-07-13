# Excluir Gemma 4 local (macOS) — manter só Qwen :11435

Wesley decree (2026-07-09): **excluir Gemma 4** — segundo `llama-server` com modelo ~2.3 GB e `-c 65536` satura 8 GB RAM e swap.

## Canonical local model (after exclusion)
- **Qwen2.5-Coder-1.5B** GGUF via `com.simplicio.local-llm` on **127.0.0.1:11435**
- Runtime env: `SIMPLICIO_LOCAL_OPENAI_BASE_URL=http://127.0.0.1:11435/v1`
- **Not** `gemma4:4b-q4_K_M` on port **8090**

## Disable permanently

```bash
USER_UID=$(id -u)
launchctl bootout "gui/${USER_UID}/com.wesleysimplicio.llama-gemma4" 2>/dev/null || true
pkill -f 'google_gemma-3-4b' 2>/dev/null || true
mkdir -p ~/Library/LaunchAgents/disabled
mv ~/Library/LaunchAgents/com.wesleysimplicio.llama-gemma4.plist \
   ~/Library/LaunchAgents/disabled/com.wesleysimplicio.llama-gemma4.plist.disabled
curl -sf --max-time 2 http://127.0.0.1:8090/health || echo "8090 down OK"
pgrep -lf llama-server   # expect only :11435 Qwen
```

## Do not re-enable at login
- Removed `RunAtLoad` by moving plist out of `~/Library/LaunchAgents/`
- To restore Gemma later: move plist back and use **`-c 8192` max** on 8 GB machines, not 65536

## User profile / memory
Update `~/.simplicio_agent/memories/USER.md` and neural store: canonical local = Qwen, Gemma excluded.

## Optional marker file
`~/.simplicio/excluded-local-models.txt` listing `gemma4:4b-q4_K_M` for operators/scripts.

## Cross-ref
OS pressure playbook: `simplicio-agent-fast-stack` → `references/macos-resource-pressure.md`