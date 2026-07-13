# GitHub issues with acceptance criteria + parallel execution (2026-07-08)

Use when the user asks to **open issues with AC** and **execute now in parallel with full runtime force**.

## Issue body template (PT-BR for user; AC as checkboxes)

Write body to `/tmp/issue-<slug>.md` then:

```bash
gh issue create --repo <owner>/<repo> \
  --title "<type(scope): short title>" \
  --label "enhancement|bug" \
  --body-file /tmp/issue-<slug>.md
```

Required sections in the body file:

```markdown
## Contexto
<why now, branch names, risk of blind merge>

## Escopo
- bullet list of commits or workstreams

## Critérios de aceite
- [ ] AC1: measurable outcome
- [ ] AC2: tests/commands
- [ ] AC3: push/main or PR link

## Fora de escopo
<what not to do>
```

## Parallel fan-out pattern

| Lane | Tool | Typical task |
|------|------|----------------|
| A | `gh issue create` × N | One issue per workstream |
| B | `delegate_task` × 3 | cherry-pick, branch delete, adapter fix |
| C | `terminal` background + `notify_on_complete` | `cargo build --release` |
| D | `mcp_simplicio_exec` / `doctor` | Evidence while git runs |

**Do not wait** on background delegations — continue local git/build; merge evidence in issue comments.

## Close issues with evidence (not narrative)

```bash
gh issue comment <n> --repo <owner>/<repo> --body-file /tmp/evidence.md
gh issue close <n> --repo <owner>/<repo> --comment "AC satisfied: <one line>"
```

When cherry-picks are all empty: close with reference to absorbing commit/PR (`a101d07f #2976` style).

## Pitfall: `gh issue comment` and shell backticks

Do **not** pass multi-line bodies with unescaped `` ` `` or `$(...)` in a single `-b "..."` string — bash will execute subshells (`doctor`, `pip`, etc.). Prefer `--body-file` for comments with code blocks or backticks.

## Pitfall: closing #2981-class issues prematurely

`simplicio-prompt` **incompatible** may need an open follow-up issue if only diagnosed (version matrix vs missing install). Close wormhole/cherry-pick issues only after **MEASURED|** command output in a comment.

## Link to runtime evolution

Branch triage and lossless sync: skill `simplicio-runtime-evolution` → `references/remote-branch-triage-and-sync.md`.