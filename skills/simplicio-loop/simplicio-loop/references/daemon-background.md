# Native daemon/background loop notes

Session note for `simplicio-loop` when applied inside `simplicio-runtime`.

## Current runtime surface
- Native command surface: `simplicio organism daemon {start|stop|throttle|status}`.
- Implementation persists daemon state under `.simplicio/organism-daemon/state.json`.
- Daemon state schema: `simplicio.organism-daemon/v1`.
- `start` prefers reusing a live persisted PID; otherwise it spawns a detached child running `organism loop --repo <repo> --cycles 1000000` with null stdin/stdout/stderr.
- `stop` terminates the persisted PID and removes state.
- `throttle` records throttled state without killing the process.

## Doc/skill implication
- In this runtime, the loop is not just a host-scheduler fallback story.
- Document the native daemon/background control surface alongside the stop-hook/self-paced fallback so future sessions do not omit the runtime-managed path.
