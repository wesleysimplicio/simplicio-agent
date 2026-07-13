# Parallel Issue Force Sweep

This reference captures a reusable workflow for high-throughput issue triage and fix sessions.

## When to use
- The user asks to resolve many issues at once.
- Issues can be clustered into independent workstreams.
- The goal is maximum safe parallelism, not serial deep dives.

## Workflow
1. Group issues into clusters by subsystem or risk.
2. Read issue bodies first; do not infer from titles alone.
3. Dispatch independent inspections/fixes in parallel.
4. Keep cleanup tasks separate from feature/bug tasks.
5. Verify after edits with real commands, not summaries.
6. Finish with `git status` and the relevant build/check command.

## Useful verification pattern
- Large command outputs should be captured to a file and then queried with targeted reads/searches.
- If a helper forwards command strings to subprocesses, pass the full argv vector intact.
  - Do not drop the first token when the helper expects a complete command line.
  - This kind of token-slicing bug can silently change behavior in status/dispatcher helpers.

## Pitfalls
- Do not treat “planned” or “dispatched” as “done”.
- Do not claim repo health without running the real check/build.
- Do not let cleanup artifacts leak into the scan/cache space; add ignore rules when appropriate.

## Notes from this session
- A status helper bug surfaced where the first token of forwarded commands was dropped before spawning subprocesses.
- Repository scans were improved by ignoring generated artifacts like decision caches, handoff files, and root-level report JSON/TXT artifacts.
- Real validation still matters even when the repo is already noisy; report the exact failure state rather than implying success.