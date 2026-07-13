# Honest Backlog Drain — quarantine, don't fake-close

Companion to the `simplicio-loop` / `simplicio-tasks` false-close pitfall (Wesley, 2026-07-11).

## The trap
When draining a large GitHub issue queue, it is tempting to close every issue whose
*body mentions a command that now returns `rc=0`*. This is false delivery at scale:
a working sub-command does not mean the issue's full ask is done. In one session this
closed 15 epics/features as "stale" — all had to be reopened.

## Quarantine-vs-close decision table
| Issue type | Closing condition | If not met |
|---|---|---|
| **Specific bug report** (label `bug`/regression) whose *exact reported failing command* now repros clean | Close with evidence comment: `simplicio --version` + the repro command + its output + `rc=0` + latency | Leave open; investigate real cause |
| **Feature request / epic / roadmap / P0-without-AC** | Close ONLY after a merged PR delivers the acceptance criteria | **QUARANTINE** — record in journal, leave OPEN |
| **Duplicate** | Close as duplicate, link canonical | n/a |

## Mandatory close-gate (never a bare `gh issue close`)
1. `gh issue view <n>` → read body + labels. Label must be a defect signal for a "stale/resolved" close.
2. Repro the *exact* failing command from the report, not a command merely mentioned in the body.
3. Evidence comment must include: `simplicio --version`, the command, `rc`, latency, and (for JSON) valid schema.
4. Live re-query confirms `state=closed` BEFORE reporting done.

## Repro engine (reusable probe)
`scripts/issue_repro_probe.py` extracts `simplicio ...` commands from issue bodies, runs
each with a hard timeout across N threads, and classifies `rc=0` / `rc!=0 (usage)` / `hang`.

```python
# scripts/issue_repro_probe.py (condensed)
import subprocess, time
def run_one(cmd, timeout=60):
    t0=time.time()
    try:
        r=subprocess.run(cmd.split(), capture_output=True, text=True, timeout=timeout)
        return {"cmd":cmd,"rc":r.returncode,"dt":round(time.time()-t0,1),
                "out":(r.stdout+r.stderr)[:200],"hang":False}
    except subprocess.TimeoutExpired:
        return {"cmd":cmd,"rc":124,"dt":timeout,"out":"TIMEOUT/HANG","hang":True}
# macOS has no `timeout` binary — use Python subprocess timeout (NOT `gtimeout`).
```

## macOS `timeout` gotcha
`timeout` is NOT installed on macOS (stock). Do NOT use `timeout 30 simplicio ...` in
shell — it fails silently with exit 0 and masks hangs. Use Python `subprocess.run(...,
timeout=60)` or install coreutils (`brew install coreutils` → `gtimeout`).

## Warning smell
If a drain shows a sudden spike of "stale" closes (e.g. 19 in one pass), STOP and
re-audit — that spike is the false-close trap. Quarantine-first, close-second.
