# Launchd in-process restart: safe path vs blocked path

Session takeaway:
- A blanket "restart blocked inside gateway" rule was too broad on macOS.
- `gateway_command("restart")` can safely handle `_HERMES_GATEWAY=1` when a launchd plist exists by delegating to `launchd_restart()`.
- `launchd_restart()` already has a self-targeted fast path: it can signal a running ancestor with `SIGUSR1`, let the gateway drain, and then rely on launchd to relaunch it.
- Keep `stop` blocked inside the running gateway; only `restart` gets the launchd-aware exception.

Verification pattern:
- Add/keep a test that asserts in-process restart on macOS calls `launchd_restart()` instead of exiting early.
- Keep a separate test that `stop` still refuses inside the gateway.

Failure mode observed:
- If the CLI blocks restart before reaching the launchd-aware helper, the gateway never comes back after a restart request initiated from inside the live process.