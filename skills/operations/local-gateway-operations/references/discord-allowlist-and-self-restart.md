# Discord allowlist + self-restart pitfall

## Durable lessons

- When liberating a Discord channel for free replies, update both:
  - `discord.allowed_channels`
  - `discord.free_response_channels`

- Validate the exact active home first. In Simplicio runs this may be `~/.simplicio_agent`, not `~/.hermes`.

- A gateway restart triggered from inside the active gateway turn can be blocked because the restart propagates SIGTERM to the running command.

## Safe restart patterns

Use one of these when the in-turn restart is blocked:
1. external terminal/session
2. detached/background helper started outside the gateway turn
3. one-shot cron/script scheduled a minute later

## Evidence to require before claiming success

- service state + PID from `launchctl` or equivalent
- fresh log line showing effective session storage path
- fresh log line showing platform connection (for example Discord connected)

## User workflow preference learned

If two path spellings differ only by capitalization or tiny typo, confirm before changing. Do not silently normalize.