# Runtime Performance Audit Notes

Use this as evidence and a repeatable audit recipe for a launchd-managed Hermes/Simplicio gateway. It is intentionally read-only unless the user explicitly requests implementation.

## Required evidence chain

Trace the actual path in order:

1. LaunchAgent plist: `ProgramArguments`, `EnvironmentVariables`, `WorkingDirectory`, `KeepAlive`, stdout/stderr destinations.
2. Wrapper: effective home, selected Python/venv, bundle path, sleeps/retries, `exec` command.
3. Live service: `launchctl print gui/$(id -u)/<label>` plus process PID/PPID/RSS/elapsed time. Treat other `gateway run` processes as distinct until their effective home and adapters are verified.
4. Startup logs: use the same boot's `Starting Hermes Gateway...` and `Gateway running with ...` timestamps; wrapper sleeps occur before the first log and must be added separately.
5. Runtime config: inspect only performance keys (streaming, session caps, MCP enablement) and never print tokens/credentials.
6. Persistence: locate live `*.db` files; inspect journal/PRAGMA read-only when storage permits; read source for connection, WAL, retry and checkpoint policy.
7. Delivery path: establish whether streaming is actually enabled before recommending stream-queue changes.

## High-value findings to look for

- A fixed launch-wrapper sleep creates a deterministic cold-start floor. Replace it only with a resource/readiness gate that preserves the original OOM/race protection.
- `WorkingDirectory` pointing at a checkout while the wrapper invokes a versioned bundle can make import resolution nondeterministic. Verify `import hermes_cli; print(hermes_cli.__file__)` with the selected bundle Python before calling the bundle immutable.
- A `max_concurrent_sessions=None` default plus a fixed executor size is not a capacity policy. Benchmark an admission cap together with the agent executor rather than raising parallelism on a low-RAM host.
- An unbounded streaming `queue.Queue` that accepts one item per model delta can amplify RAM/GC pressure when outbound platform edits slow down. Coalescing/bounded delivery must retain the final accumulated text.
- A periodic SQLite `wal_checkpoint(TRUNCATE)` can improve disk use yet create p95 write stalls. On constrained machines, require free-space headroom before moving checkpoint work to idle/background; measure WAL growth and write latency together.
- Disk exhaustion is a correctness and performance incident, not merely maintenance: it can prevent atomic auth/config writes, logging, SQLite checkpoints, temporary file creation, and therefore invalidate live benchmarks.

## Benchmark definitions

- `T_ready`: `t("Gateway running with") - t(launchctl kickstart -k ...)`; run at least 20 cold starts. Report p50/p95. Add known wrapper delay explicitly if the first log is emitted after it.
- `T_first_visible`: timestamp of first successfully visible platform create/edit/draft minus inbound event receipt. This is the relevant perceived TTFT for messaging platforms.
- Concurrency sweep: N = 1, 2, 3, 4, 6, 10 equivalent turns; report p50/p95 `T_first_visible`, p95 completion time, max RSS, memory pressure/compression/swap, platform errors, and SQLite retries.
- SQLite: record p95 write duration, checkpoint duration, retry count, and max WAL bytes.
- Streaming: record max queue depth, delta-to-visible p95, edit count, and final-text equality.

Do not run restart/load benchmarks during an audit-only request. Present the exact metric and procedure as a proposed validation plan.
