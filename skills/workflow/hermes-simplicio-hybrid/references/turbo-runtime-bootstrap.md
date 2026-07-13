# Hermes Turbo / .hermes_turbo Bootstrap Reference

Use this when the user wants a clean-room hybrid runtime that is **Hermes original + Simplicio completo**, not a forked identity.

## Identity rule

Always describe the architecture as:

- **Hermes original** = ouvidos, entrada, cérebro, raciocínio, conversa, coordenação.
- **Simplicio completo** = olhos, braços, mãos, execução, validação, automação, evidência.

Do **not** describe it as:

- "Hermes modificado"
- "fork mais rápido"
- "substituto do Hermes"

## Zero-reset bootstrap pattern

1. Remove the old project clone.
2. Remove the dedicated runtime home (for example `~/.hermes_turbo`).
3. Clone the latest upstream `NousResearch/hermes-agent` into a fresh target directory.
4. Create a project-local venv.
5. Install editable Hermes with **messaging extras** so Discord deps are actually present.
   - Pitfall: `.[discord]` is not a valid extra in current upstream packaging; install `.[messaging]`.
6. Create a dedicated `HERMES_HOME` such as `~/.hermes_turbo`.
7. Copy only the auth/config pieces you truly want to inherit (for example `auth.json`), not the whole old home blindly.
8. Write a dedicated `config.yaml` and `SOUL.md` that encode the hybrid role split.
9. Point terminal/workdir toward the Simplicio runtime repo when that is the intended execution body.
10. Create a dedicated launchd wrapper + plist that export the dedicated `HERMES_HOME`.
11. Start the dedicated gateway service.
12. Verify logs, not just config status.

## Dedicated-home pitfalls

### 1) `hermes status` is not enough

`hermes status` can show **Discord configured** even when login is failing. Treat it as config presence, not connection proof.

For connection truth, inspect the gateway logs and require evidence such as:

- successful Discord ready/connected lines, or
- explicit failure such as `LoginFailure`, `401 Unauthorized`, or startup conflicts.

### 2) Strip unrelated platform env from the dedicated home

If you copy `.env` from another Hermes home, remove platform variables that are not intentionally part of the dedicated runtime.

Important example from this session:

- inherited `WHATSAPP_*` variables caused gateway startup conflict in the new `.hermes_turbo` home because WhatsApp was enabled but not paired.
- fix: remove the `WHATSAPP_*` entries from the dedicated `.env` if the runtime is meant to run Discord only.

### 3) Dedicated Discord token may still be stale

A clean bootstrap can succeed structurally while Discord still fails with:

- `discord.errors.LoginFailure: Improper token has been passed`
- `401 Unauthorized`

That means the runtime wiring is up, but the bot token itself must be replaced or reissued. Do not claim the bot is online until log evidence confirms connection.

## launchd pattern

Use a dedicated wrapper script that:

- exports `HERMES_HOME=<dedicated home>`
- prepends the project venv to `PATH`
- runs `python -m hermes_cli.main gateway run --replace`

Then point a dedicated LaunchAgent plist at that wrapper. Keep the service label distinct from the default Hermes gateway.

## Verification checklist

- Upstream Hermes cloned fresh
- venv created
- `.[messaging]` installed successfully
- dedicated `HERMES_HOME` created
- hybrid `config.yaml` + `SOUL.md` written
- dedicated launchd service loaded
- unrelated platform vars removed from dedicated `.env`
- gateway log checked
- Discord proven connected by log evidence before declaring success
