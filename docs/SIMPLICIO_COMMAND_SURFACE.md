# Simplicio Runtime — Complete Command Surface

Generated from `simplicio --help` (runtime 3.5.0). Agents must consult this file before inventing a command; use `simplicio <command> --help` for the live contract.

Total documented command signatures: **111**.

```text
simplicio doctor [--json] [--repo <path>] [--repair] [--capabilities]
simplicio toolchain [--json]
simplicio endpoints compare --web <dir> --api <dir> [--agents-dir <dir>] [--format markdown|json]
simplicio pr status|open|update-evidence --repo <path> [--json]
simplicio precedent init|index|status|search|check --repo <path> [--from-runs <path>] [--text <query>] [--precedent <id-or-path>|--issue <n>] [--top N] [--json]
simplicio issue-worktree prepare|status|cleanup --repo <path> [--issue N] [--run-id ID] [--force] [--json]
simplicio issue-factory run --repo <path> --source github [--max-parallel N] [--reuse-precedents] [--evidence] [--json]
simplicio cloud-watch [--repo <path>] [--json]
simplicio evidence web --flow <name> --base-url <url> [--json]
simplicio issue-factory discover|claim|pr-handoff|comment --repo <path> [--json]
simplicio runtime map [--json|--for-llm markdown|--for-llm json|--for-llm toon] [--repo <path>]
simplicio infra-advanced [--json]   experimental preview for module hot-reload
simplicio contracts smoke [--json] [--repo <path>]
simplicio runtime smoke [--json] [--repo <path>]
simplicio exec-graph run|status|define|validate|dot [--json] [--repo <path>]
simplicio map --repo <path> [--json]
simplicio plan "<task>" --repo <path> [--agents N] [--json]
simplicio decide "<task>" --repo <path> [--json]
simplicio run "<task>" --repo <path> [--agents N] [--local|--remote] [--evidence]
simplicio sprint <sprint-path-or-text> --repo <path> [--agents N] [--evidence] [--pr] [--watch] [--reuse-precedents]
simplicio sprint send --issue <n> --repo <path> --reuse-precedents --evidence --json
simplicio workflow list|run|status|watch|events|resume|retry|evidence|failures [<workflow_id>] [--repo <path>] [--view compact|detail] [--json]
simplicio issue-factory mvp --repo <path> --fixture examples/issue-factory/mvp [--reuse-precedents] [--evidence] [--json]
simplicio edit --plan <plan.json|-> [--file <path>] [--repo <path>] [--dry-run] [--review] [--commit <msg>] [--json]
simplicio edit '{"file":"...","operations":[...]}' [--dry-run] [--review] [--commit <msg>] [--json]
simplicio edit --plan <plan.json|-> [--build <cmd>] [--render <cmd>] [--assert <cmd>] [--check <cmd>] [--repo <path>] [--review] [--commit <msg>] [--json]
simplicio exec "<simplicio subcommand>"              gated runtime subcommand router; no raw shell
simplicio runtime map [--json | --for-llm] [--repo <path>]
simplicio self-mutation status|maintenance|handoff [--repo <runtime>] [--json]
simplicio agents status [--agents N] [--machine-profile <name>] [--json]
simplicio agents delegate <goal>|--file tasks.json | children | pause|resume|interrupt [--json]
simplicio dev-cli "<task>" --repo <path> [--target <file>] [--stack <stack>] [--remote] [--json]
simplicio model status|check <file>|smoke [--json]
simplicio benchmark run|measure [--sample] [--json]   (run = measured timings; --sample = fixture rows)
simplicio benchmark savings [--json]
simplicio issue-factory benchmark --repo <path> --fixture examples/issue-factory [--json]
simplicio issue-factory metrics --repo <path> --last 10 [--json]
simplicio savings report --repo <path> [--user <id>] [--team <id>] [--model <id>] [--proof-kind <kind>] [--json]
simplicio savings compare --with-simplicio <run-dir> --without-simplicio <baseline.json> [--proof-kind replayed|measured|benchmark] [--json]
simplicio savings record --spent <N> --baseline <N> [--source codex] [--task <desc>] [--model <id>] [--provider <id>] [--proof-kind measured|estimated|replayed|benchmark] [--json]
simplicio savings prove [--repo <path>] [--run-id <id>] [--json]
simplicio savings pricing [--model <provider/model>] [--json]
simplicio savings whoami [--repo <path>] [--json]
simplicio savings export --format json|csv|markdown [--repo <path>] [--json]
simplicio savings dashboard --repo <path> [--json]
simplicio savings sync --dry-run [--endpoint <url>] [--repo <path>] [--json]
simplicio savings sync --yes --endpoint <url> [--repo <path>] [--json]
simplicio shell [compact] [--json] [--no-spill] [--repo <path>] -- <cmd> [args...]  supervised external command runner
simplicio compact text <text> [--json] | compact file <path> [--output <path>|--write] [--json]
simplicio packages update [--dry-run] [--json] | bundle [--json]
simplicio update auto status|check [--window morning|night] [--json] | update check|apply|rollback|sign <sha256> [--json]
simplicio cron status|list|add|tick|run|pause|resume|remove [--json]
simplicio login google [--json] | auth status [--json] | logout [--json]
simplicio license status [--json]
simplicio telegram send "<msg>" | report | listen | status [--json]
simplicio discord send "<msg>" | guilds | channels | messages | server-info | roles | pins | member-info | search-members | thread | pin | unpin | delete | add-role | remove-role | status [--json]
simplicio browser status|navigate <url>|snapshot|click|type|scroll|back|press|images|vision|console [--json]
simplicio browser connect --cdp <http://127.0.0.1:9222>|disconnect|cdp --method <CDP.method>|dialog --action accept|dismiss [--json]
simplicio computer-use status|capture|click|double_click|right_click|drag|scroll|type|key|set_value|wait|list_apps|focus_app [--json]
simplicio validate "<task>" --repo <path> [--json]
simplicio diagnostics --repo <path> [--toolchain rustc|clippy|tsc|pytest|pyright] [--from-file <log>] [--json]
simplicio trajectory record <session> --intent <i> --outcome green|red|blocked [--exec-command <c>] [--task-kind <k>] [--errors N] [--warnings N]
simplicio trajectory show <session> [--repo <path>] [--json]
simplicio trajectory suggest [<session>] [--repo <path>] [--json]
simplicio task normalize "<task>" --repo <path> [--json]
simplicio evidence show --run-id <id> [--json]
simplicio status [--json] [--watch] [--interval-ms <ms>] [--samples <n>]
simplicio governor simulate --repo <path> [--agents N] [--json]
simplicio parallelism --repo <path> [--agents N] [--json]
simplicio cache clear [--json]
simplicio memory status|init|query [--backend sqlite-fts5|sqlite-vec|lancedb|qdrant-edge] [--json]
simplicio memory-db "<task>" --repo <path> [--json]
simplicio skill-memory "<task>" --repo <path> [--json]
simplicio orientation status|pack --repo <path> [--json]
simplicio capabilities list [--json]
simplicio capabilities rank "<task>" [--json]
simplicio chat "<message>" --repo <path> [--local] [--json]
simplicio chat --repl --repo <path>
simplicio chat --openai < openai-chat-completions.json
simplicio chat --anthropic < anthropic-messages.json
simplicio invoke [--json]
simplicio advise "<task>" --repo <path> [--json]
simplicio compiled --repo <path> [--json]
simplicio learn from-run <run-id> [--scope project|local|global] [--yes]
simplicio benchmark run --sample [--json]
simplicio intake "faça todas as tasks da sprint <link>; o repositório é <path>" [--json]
simplicio integrations intake|audit|guard|broker|manifest --repo <path> [--json]
simplicio install --global [--dry-run] [--json]
simplicio app list|info <name>|doctor <name>|setup <name>|run <name> [--json]
simplicio completion [bash|zsh|fish] [--json]
simplicio serve [--mcp|--http|--stdio] [--json]
simplicio contracts smoke [--json]
simplicio update check|apply|rollback|status|sign <sha256> [--json]
simplicio welcome [--json]
simplicio self-test [--json]
simplicio version [--json]
simplicio security [--json]                           Audit supply-chain (Cargo.lock + plugins + MCP)
simplicio backup [--quick] [--output <zip>] [--label <name>]  Create zip backup
simplicio restore <zip> [--target <dir>]              Restore from zip
simplicio hooks list|test|revoke|doctor [--json]      Manage shell hooks
simplicio proxy start|status|providers [--json]       Proxy server lifecycle
simplicio pairing list|begin|verify|approve|revoke    Device pairing (challenge-response)
simplicio recover "<cmd>" [--attempts N]             Run a command with classified retry/backoff
simplicio setup                                       First-run wizard (.simplicio/ + config + probes)
simplicio dump                                        Write a diagnostics dump under .simplicio/dump/
simplicio memory-v2 status|init|store|search|count    Native Rust memory layer (rusqlite + FTS5)
simplicio invoke --json
simplicio compiled --json
simplicio advise "<task>" --json
simplicio install --global --dry-run --json
simplicio-agent mcp serve   # sole public MCP gateway; Runtime MCP is internal only
```
