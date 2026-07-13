# Server-wide Discord channel rollout

Use this when the user wants a Hermes/Simplicio Discord bot enabled in **all channels of one server**.

## Verified pattern

1. Confirm the real gateway home from the launcher/start script (`HERMES_HOME` may be `~/.simplicio_agent`, not `~/.hermes`).
2. Query the Discord API for the guild's channels and filter to text-capable channel types instead of trusting names from memory.
3. Build the full comma-separated ID list.
4. Write the same list to both:
   - `discord.allowed_channels`
   - `discord.free_response_channels`
5. Restart the gateway **outside** the live gateway turn.
6. Verify with fresh evidence:
   - `launchctl`/service state + PID
   - session storage path in the gateway log
   - fresh `[Discord] Connected as ...`
   - fresh `✓ discord connected`
   - fresh `Channel directory built: N target(s)`

## Practical notes

- If the user also names one extra channel ID explicitly, verify that channel too instead of assuming it belongs to the same server.
- For one-shot cron restarts, the script path must be relative to `~/.hermes/scripts/`.
- One-shot cron jobs may not remain visible in later `cron list`; if you need proof, keep the returned `job_id` and inspect/run it immediately.

## Typical text-capable channel filter

For Discord API channel payloads, a practical filter is to keep channel types commonly used for text work (for example normal text + announcement + thread/forum-style text surfaces if relevant to the environment) and exclude voice/stage/category-only objects.

## What to report back

Prefer concise evidence-only reporting:
- channel count discovered
- whether the named channel ID was confirmed
- exact service state / PID
- exact post-restart connection lines from the log
