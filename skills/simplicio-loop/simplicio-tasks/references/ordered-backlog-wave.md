# Ordered backlog wave

Use this recipe when a user asks to drain open issues across multiple repositories and specifies an execution order.

## Procedure

1. Enumerate the authoritative repositories and query live open issue counts with the source API. Exclude explicitly excluded repositories before sorting.
2. Build lanes as `(open_count, repository_name, repository_path)` and sort ascending by count, then repository name.
3. Start only the first lane. Use the native runtime issue/work factory with evidence enabled and a bounded parallelism cap.
4. Inspect the returned state before advancing. `running` is not completion; `completed_fixture`, `planned`, `queued`, and `throttled` are not delivery evidence.
5. Advance to the next lane only after the prior lane has a real terminal result or an explicitly recorded blocker. Keep the requested order even when lanes have equal counts.
6. For each claimed item, require: real code change or justified no-code resolution, PR/commit handle, passing validation/evidence receipt, and live issue re-query. Only then count it as delivered or close it.
7. If the runtime reports fixture/simulation output, report it as fixture evidence and leave the source issue open. If it throttles, record the reason (for example worktree/resource limit) separately from successful work.

## Evidence vocabulary

- `MEASURED| lane started`: runtime returned a live run/state handle.
- `MEASURED| delivered`: PR/commit + validation receipt + live source re-query exist.
- `UNVERIFIED| completed_fixture`: fixture/scheduler path ran, but no production delivery was proven.
- `UNVERIFIED| throttled`: the runtime admitted less work than requested or deferred work due to governance.

Never convert a fixture result, a zero-error command, or a scheduler acknowledgement into an issue close. The source of truth remains the live issue/PR state.