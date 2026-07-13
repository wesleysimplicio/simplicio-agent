# Dev-task loop pattern — orphaned-PR merge within one loop iteration

Concrete, reproducible recipe for handling a dev task (merge a PR, close an issue,
implement a feature) as a REAL `simplicio-loop` iteration instead of a `delegate_task`
/ `execute_code` bypass that produces partial delivery. Distilled from a 2026-07-11
session that closed `dev-cli#153` (orphaned PR for issue/129 recovery fixtures) and
the policy "relate mas não feche" (keep related issue open).

## Trigger
Any dev task with an acceptance criterion → arm the loop. Do NOT use `delegate_task`
or a bare `execute_code` git/gh flow. The loop's close-gate (live re-query + evidence)
is what prevents partial delivery.

## Loop state (arm first — scratchpad on disk = loop armed)
```
mkdir -p .orchestrator/loop
cat > .orchestrator/loop/scratchpad.md <<'EOF'
---
iteration: 1
max_iterations: 12
completion_promise: "<EXACT TEXT the goal satisfies>"
evidence_required: true
mode: drain            # drain for a queue; converge for a single hard task
started_at: "<ISO-8601>"
---
<goal verbatim>
EOF
echo '{"match":false,"status":"UNVERIFIED"}' > .orchestrator/loop/watcher_state.json
touch .orchestrator/loop/journal.jsonl
```

## Step-by-step (operate + verify in the SAME turn)

### 0. Preflight — confirm runtime bound
```bash
simplicio doctor --json     # overall_status: ok required before iteration 1
```

### 1. Triage the live git state FIRST (mandatory)
A merge will fail if there is unrelated local WIP. Detect it before acting:
```bash
git status --short
git diff --stat
```
If there is unrelated WIP that would block the operation (e.g. `git merge` aborts with
"Your local changes would be overwritten"), **stash it** so the loop's real change merges clean:
```bash
git stash push -m "loop-iterN-preserve-<topic>-wip"
git pull --ff-only origin <base>     # now clean
```
Restore it AFTER the loop's change is merged + verified (step 5).

### 2. Decide: merge vs close-documentado
Before merging, confirm the PR head is NOT already in the base. If reachable → GitHub
auto-closes on push; if not → needs merge. If it's already contained, just document.
```bash
git fetch origin <pr-head> <base>
git merge-base --is-ancestor origin/<pr-head> origin/<base> \
  && echo "ALREADY in base (obsolete/merged)" \
  || echo "NEEDS merge"
```

### 3. Operate — apply the decided change
```bash
git checkout <base> && git pull --ff-only origin <base>
git merge origin/<pr-head> --no-ff -m "Merge PR #N: <title>" --no-edit
git rev-parse HEAD
```

### 4. Evidence gate — "works, not just compiles"
Run the PR's own tests. **Pitfall:** the system `python3` may be <3.10.
If you see
```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```
on import, the active interpreter is <3.10 (e.g. macOS `/usr/bin/python3` = 3.9.6).
Switch to the repo-required Python (this repo requires 3.10+; use
`/opt/homebrew/bin/python3.11` on this Mac):
```bash
/opt/homebrew/bin/python3.11 -m pytest tests/python/test_mapping_retry_flow.py -q
# expect: 33 passed  (MEASURED| evidence)
```
The test pass IS the in-turn evidence the promise gate needs.

### 5. Push + close-gate (live re-query — NOT a self-reported "done")
```bash
git push origin <base>
gh pr view <N> --repo <owner>/<repo> --json state,mergedAt,mergeCommit
# GitHub auto-detects the merge async; poll up to 3x if it still shows OPEN:
for i in 1 2 3; do sleep 4
  gh pr view <N> --repo <owner>/<repo> --json state,mergedAt,mergeCommit
done
# MEASURED| when state == MERGED and mergeCommit matches the local HEAD
```

### 6. Policy — keep related issue open if that was the rule
```bash
gh issue view <related> --repo <owner>/<repo> --json state
# EXPECTED: OPEN (policy "relate mas não feche" — do NOT auto-close)
```

### 7. Restore preserved WIP + resolve any stash conflict
```bash
git stash pop
```
If `git stash pop` leaves a conflict in an **append-only JSON-L ledger** (e.g.
`.simplicio/ledger/savings-events.jsonl`), resolve deterministically:
- The file is one JSON object per line. Conflict markers split two added blocks.
- Take `base` (lines before `<<<<<<<`) + both sides' new lines, then **sort the new
  lines by their `ts` field** and concatenate. Validate every line parses as JSON.
- This preserves both agents' events without loss. (`_valid(l)` = `json.loads(l)`)
```python
import json, re
raw = open(p).read()
m = re.search(r"<<<<<<< .*?\n(.*?)=======\n(.*?)>>>>>>> .*?\n", raw, re.S)
ours, theirs = m.group(1).rstrip("\n").split("\n"), m.group(2).rstrip("\n").split("\n")
base = [l for l in raw.split("<<<<<<<")[0].rstrip("\n").split("\n") if l.strip()]
new = sorted([l for l in ours+theirs if l.strip()],
             key=lambda l: (json.loads(l).get("ts","") if l.strip() else ""))
open(p,"w").write("\n".join(base+new)+"\n")
# assert: all lines json.loads OK, no conflict markers remain
```
Then `git add <ledger>` and `git stash drop`.

### 8. Record + watcher-gate + done
```bash
# journal.jsonl append: {iteration, action, hypothesis, gate:"pass", gate_output, promise_satisfied}
# watcher_state.json: {"match":true,"status":"MEASURED","challenge":"PR#N merged?",
#                       "evidence":"gh pr view -> MERGED <sha>; related issue OPEN"}
touch .orchestrator/loop/done
```
Only now emit the sentinel:
```
<promise>EXACT TEXT from completion_promise</promise>
```

## Anti-patterns caught by this pattern
- Reporting "done" from `delegate_task` without a live GitHub re-query → partial delivery.
- Running repo tests under system `python3` (3.9) → `|`-operator TypeError; always use the
  repo-required interpreter.
- Dropping unrelated local WIP instead of `git stash` → lost work or a dirty merge.
- Hand-resolving a JSON-L ledger by picking one side → lost events; ts-sorted concat keeps both.
- Auto-closing a related issue that policy says to keep open → violate "relate mas não feche".
