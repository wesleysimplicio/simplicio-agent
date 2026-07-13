# Release Monitoring via Cron Job

Pattern for setting up an automated release monitor that checks the pipeline
status periodically and posts updates to Discord.

## When to use

- During an active release cycle when you want ongoing visibility into whether
  the site, GitHub Releases, and git tags are aligned
- When a release is done on GitHub but site deploy hasn't happened yet
- When tracking whether a pipeline is "green start to finish"

## What the monitor checks

1. **Cargo.toml version** — the canonical source of truth
2. **Git tags** — latest tag vs Cargo.toml version
3. **Commits since last tag** — unpushed / post-release work
4. **GitHub Releases** — whether the expected tag has a release (`gh release list`)
5. **Site version.txt** — what's actually deployed (`simpleti.com.br/simplicio/version.txt`)
6. **Site binary** — HTTP status of `dist/simplicio-darwin-arm64`
7. **State change detection** — only post to Discord if something actually changed

## Cron job setup

```bash
hermes cron create \
  --name "Simplicio Release Monitor" \
  --schedule "every 2h" \
  --workdir /Users/wesleysimplicio/Projetos/ai/simplicio-runtime \
  --enabled-toolsets web,terminal,file \
  --prompt "Monitor the Simplicio Runtime release and publication status..."
```

Key parameters:
- `workdir`: run from the repo so git commands work
- `enabled-toolsets`: pin to only what the monitor needs (saves tokens)
- `schedule`: every 2h is fine for release tracking; every 30m during active deploys

## Discord notification pattern

Use emoji markers and keep messages concise:

```
🟢 = done/up-to-date
🔴 = missing/pending
🟡 = in progress
```

Format:
```
📡 **Release Monitor — <timestamp>**

• Cargo.toml: `1.0.2`
• GitHub Release: `v1.0.2` ✅
• Site (simpleti.com.br): `1.0.0` 🔴 **deploy pendente**
• N commits após o último tag
```

Always send via `send_message` to `discord:#simplicio-runtime`.

## State change detection

Cron jobs run in isolated sessions with no memory of the previous run. To only
notify on state changes, the prompt MUST instruct the agent to gather current
state and compare against known snapshots. Two approaches:

**Approach A (simpler):** Check if there are any gaps at all and always report.
Good for active release windows where every tick is expected to show progress.

**Approach B (tokens — not yet implemented):** Write the last-known-state to
a file like `/tmp/simplicio-release-state.json` and compare before sending.
This requires the cron job to read and write a state file each tick.

## Pitfalls

- **GitHub API rate limits:** `gh release list` counts against the CLI quota.
  Use `curl` to the API if you expect heavy polling.
- **Site returns HTML 404 as 200:** HostGator returns a 200 with an HTML page
  for missing files. The monitor must validate the response content (starts with
  a digit for version.txt).
- **Cron jobs are isolated:** Each run is a fresh session — no persistent
  variables. Design the prompt to be fully self-contained.
- **Over-notification:** A monitor that reports "same gap again" every 2h is
  noise. Always include "only if state changed" in the prompt.

## Example output

```
📡 Monitor de Release — Atualização

Estado atual:
🟢 Cargo.toml: 1.0.2
🟢 GitHub Release: v1.0.2 (Autopilot v5)
🔴 Site: 1.0.0 — deploy FTP pendente
🟡 4 commits após o último tag

➡️ Próxima verificação em ~2h
```
