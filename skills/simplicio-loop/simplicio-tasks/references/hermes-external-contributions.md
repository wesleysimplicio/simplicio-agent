# Hermes Agent — External Contribution Guide

## Pattern: Parallel PR Batches via Subagents

The fastest way to contribute multiple PRs to Hermes Agent is **mechanical refactors distributed across parallel delegate_task agents**. Each agent handles ONE batch of similar changes across multiple files. Average throughput: **3-5 PRs per agent batch in ~20min**.

### Validated PR types (all accepted, ranked by speed)

| Speed | Type | Pattern | Example PRs |
|-------|------|---------|-------------|
| ⚡ | **Idiomatic Python** | `len(x) == 0` → `not x`; `len(x) > 0` → truthy `x` | #58842, #58896, #58898, #58900, #58901 |
| ⚡ | **Docs fixes** | Broken URLs, stale permission integers, outdated refs | #58890, #58903 |
| ⚡ | **`dict()`→`{}` / `list()`→`[]`** | Empty constructor → literal | (pattern ready) |
| ⚡ | **Unused imports** | Remove imports confirmed unused via grep | (pipeline ready) |
| 🐢 | **Dead code** | Remove unreachable branches, unused functions | (complex, skip for volume) |

### The Top-5 Contributor Pattern (real data)

| Rank | Contributor | Commits | Strategy |
|------|-------------|---------|----------|
| 1 | teknium1 | 6180 | Salvages community PRs, cherry-picks + rebases. **He is the gatekeeper** |
| 2 | OutThisLife | 1448 | Thousands of small fixes over months. **Consistency > burst** |
| 3 | kshitijk4poor | 746 | Large salvages + consistent commits. **Depth > breadth** |
| 4 | benbarclay | 321 | Core contributions, specialized areas |
| 5 | helix4u | 213 | Focused fixes, steady cadence |

**Key insight:** The real pattern is **consistency + specialization + quality**, NOT quantity spikes. liuhao1024 does 3 PRs/day but EVERY day. kshitijk4poor does large salvages but well-crafted.

### Pipeline: N parallel agents = N PRs in ~5 min

```python
# Batch: 3-5 agents, each handles one pattern across different files
tasks = [
    {"goal": "PR: idiomatic Python in gateway/..."},
    {"goal": "PR: idiomatic Python in hermes_cli/..."},
    {"goal": "PR: idiomatic Python in skills-plugins/..."},
    {"goal": "PR: dict() → {} in agent/hermes..."},
    {"goal": "PR: list() → [] in tools/..."},
]
delegate_task(tasks=tasks)  # all run in parallel
```

### 5-Minute Monitoring Cycle

Set up a cron job that every 5 minutes:
1. Counts our open PRs: `gh search prs --repo <repo> --author <user> --state open --json number`
2. If count < 10, finds the next issue without a linked PR
3. Checks issue timeline for existing PRs before creating a new one
4. Alerts here when new candidates appear

### CRITICAL PITFALLS (learned the hard way)

1. **⚠️ NEVER create duplicate PRs — ever.** This is the #1 reputation killer. Before EVERY PR:
   ```bash
   # Check our existing PRs
   gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio --state open
   # Check if someone else already has the fix
   gh api "repos/NousResearch/hermes-agent/issues/<N>/timeline" \
     --jq '[.[] | select(.source and .source.issue and .source.issue.pull_request) | .source.issue.number]'
   ```
   **Real failure:** PR #58885 was a duplicate of #58877 (liuhao1024 beat us by 2 min). Had to close it immediately.

2. **⚠️ Subagents fail on partial errors.** One agent that fails on 1 of 19 files skips the entire PR. Strategy: keep batches **small (3-5 files max per agent)** and verify each returned a PR number. Do NOT send 19-file batches.

3. **⚠️ No salvage of old (>2 week) PRs.** The diff runs into hundreds of thousands of lines of conflicts. Teknium (the maintainer) can do this because he knows every line. We cannot.

4. **⚠️ 100 PRs/day is NOT feasible on a single repo.** There simply aren't enough bugs. Hermes Agent gets ~20-30 PRs/day merged at peak. For more volume, expand to multiple repos in the ecosystem.

5. **✅ Docs fixes are the safest bet.** Zero code review needed, no runtime validation, always welcome. Pattern: search for broken URLs, stale permission integers (like #40389), or 160KB copy-pasted API docs (like pytorch-fsdp.md).

6. **✅ Cron monitoring beats raw speed.** The window between "issue created" and "PR submitted" is ~30 min for the top competitors. A 5-min cron that alerts us is our best strategy.

### Useful Commands

```bash
# List all our open PRs
gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio --state open --json number,title

# Check if an issue has a linked PR
gh api "repos/NousResearch/hermes-agent/issues/<N>/timeline" \
  --jq '[.[] | select(.source and .source.issue and .source.issue.pull_request) | .source.issue.number]'

# Find all issues without PRs (bugs first)
gh api "repos/NousResearch/hermes-agent/issues?state=open&labels=type%2Fbug&sort=created&direction=desc&per_page=10" \
  --jq '.[] | select(.pull_request == null) | [.number,.title,.created_at] | @tsv'

# Quick py_compile check
python3 -m py_compile <file.py>

# Target repo info
REPO=NousResearch/hermes-agent
CONTRIBUTING=$REPO/CONTRIBUTING.md  # Read this first
AGENTS=$REPO/AGENTS.md  # AI assistant development guide
PR_TEMPLATE=$REPO/.github/PULL_REQUEST_TEMPLATE.md  # Required PR body format
```
