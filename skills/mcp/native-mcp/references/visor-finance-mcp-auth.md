# Visor Finance MCP auth notes

Use when the remote MCP server is `https://dashboard.visorfinance.app/mcp`.

## Observed behavior

- `GET /mcp` without auth returns `401 Unauthorized`
- `WWW-Authenticate` points to:
  - `resource_metadata="https://dashboard.visorfinance.app/.well-known/oauth-protected-resource"`
- Protected-resource JSON currently returns:

```json
{
  "resource": "https://dashboard.visorfinance.app/mcp",
  "authorization_servers": ["https://dashboard.visorfinance.app"],
  "bearer_methods_supported": ["header"]
}
```

- Root app redirects unauthenticated users to `/login?session_expired=1`
- Login page offers:
  - Google
  - Apple
  - email + password

## Important limitation

In Hermes logs, a common failure mode is:

- `MCP OAuth for 'visor': non-interactive environment and no cached tokens found`

Practical meaning:
- the MCP is configured
- the server requires auth
- Hermes has no cached Visor token yet
- unattended/background retries will keep failing with `401 Unauthorized`

## Practical guidance

1. Treat Visor as **configured but not authenticated** until a real login completes.
2. If running inside a non-interactive environment, do not promise that Hermes can finish auth alone.
3. Use an interactive browser session first and have the user complete one of the offered login methods.
4. After successful login/auth, retest with:

```bash
hermes mcp test visor
```

5. If it still fails, inspect fresh log lines for `visor` in `~/.hermes/logs/errors.log*`.

## Known-good verification probes

```bash
hermes mcp list
hermes mcp test visor
curl -i https://dashboard.visorfinance.app/mcp
curl https://dashboard.visorfinance.app/.well-known/oauth-protected-resource
```

## What not to assume

- Do not assume device flow endpoints exist just because the server is OAuth-protected.
- Do not assume Hermes can complete first-time auth from a non-interactive cron/gateway context.
- Do not claim read access to spending/budget data until `hermes mcp test visor` succeeds.
