# Local stdio MCP server across Claude Code, Codex, and Hermes

Use this when the MCP server is a local repo you cloned (Node/Bun/Python) and you want the same server available in multiple agent clients.

## Practical defaults

- Use **absolute paths** for both the runtime binary and the server entrypoint.
- Prefer the real Bun path (for example `$(command -v bun)`) instead of plain `bun` when configuring GUI apps or background agents.
- Put secrets in MCP config env vars, not as CLI args.
- After adding a server, verify with each client's `mcp list` / `mcp get` command before assuming it is usable.

## Claude Code

For stdio servers with env vars, `claude mcp add` can be finicky when mixing `-e` flags with the `-- <command> ...` separator. The most reliable path is `add-json`.

Example:

```bash
python3 - <<'PY'
import json, subprocess
cfg = {
  "type": "stdio",
  "command": "/ABSOLUTE/PATH/TO/bun",
  "args": ["/ABSOLUTE/PATH/TO/server-entry.ts"],
  "env": {"API_KEY": "***"}
}
subprocess.run([
  "claude", "mcp", "add-json", "-s", "user", "my-server", json.dumps(cfg)
], check=True)
PY
```

Verify:

```bash
claude mcp get my-server
claude mcp list
```

## Codex

Codex CLI works well for local stdio servers with inline env vars.

```bash
codex mcp add my-server --env API_KEY=*** -- /ABSOLUTE/PATH/TO/bun /ABSOLUTE/PATH/TO/server-entry.ts
codex mcp get my-server
codex mcp list
```

## Hermes

Try the native add command first:

```bash
hermes mcp add my-server \
  --command /ABSOLUTE/PATH/TO/bun \
  --args /ABSOLUTE/PATH/TO/server-entry.ts \
  --env API_KEY=***
```

Important pitfall:
- some Hermes versions connect successfully and then prompt to enable discovered tools
- if that prompt is cancelled, the server may **not persist** to `~/.hermes/config.yaml` even though the one-shot connection succeeded

Reliable fallback: write the server directly to `~/.hermes/config.yaml` under `mcp_servers`.

```yaml
mcp_servers:
  my-server:
    command: /ABSOLUTE/PATH/TO/bun
    args:
      - /ABSOLUTE/PATH/TO/server-entry.ts
    env:
      API_KEY: "***"
    enabled: true
```

Then verify:

```bash
hermes mcp list
```

If Hermes is already running (CLI or gateway), start a new session or restart the relevant process so the MCP inventory reloads.

## Validation pattern

1. Clone repo and install dependencies (`bun install`, `npm install`, etc.).
2. Verify the entrypoint directly if needed.
3. Register in each client.
4. Run `claude mcp get <name>`, `codex mcp get <name>`, and `hermes mcp list`.
5. Only after config is confirmed should you debug auth/tool behavior.

## Session-specific note that generalized well

A real Bun-based server (`abacatepay-mcp`) exposed tools correctly in Codex and Claude immediately, but Hermes needed the config-file fallback after the interactive enable-tools step was cancelled. Treat that as a general persistence pitfall for local stdio MCP setup, not as a server-specific bug.