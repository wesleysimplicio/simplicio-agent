---
name: continuous-swarm-supervisor
description: Use when evolving a terminal/chat interface (TUI) into a continuous, proactive, multi-agent swarm with Hermes-like capabilities. Covers persistent looping, agents delegate, rich tool calling, vector memory, proactivity, provider/model selection, vision, generation, web search, and rich panel simulation. This skill encodes the full workflow for making a runtime like Simplicio have full Hermes Agent parity.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [terminal, swarm, looping, hermes-parity, multi-agent, proactivity, vector-memory, tool-calling, tui]
    related_skills: [hermes-agent, hermes-agent-skill-authoring, terminal-ops]
---

# Continuous Swarm Supervisor

## Overview

This skill governs the class of work where you evolve a terminal/chat interface (TUI) into a continuous, proactive, multi-agent swarm that has full Hermes Agent parity.

It encodes the complete workflow, pitfalls, and lessons from a long session where the user repeatedly corrected the approach ("stop using simplicio for everything, use yourself", "use the binary", "in looping", "enxame de agents", "looping pensativo", "faca todos sem parar", "implemente de verdade", "ajuste para funcionar", "faca do simplicio melhor em tudo").

The target outcome is a TUI that:
- Runs in continuous evolutionary looping with a swarm of agents (64-600)
- Has rich tool calling with JSON, loading, formatted results
- Has real vector memory with SQLite + semantic search
- Has proactivity (suggests next steps without being asked)
- Has natural conversation, creative reasoning, broad knowledge connection
- Has integrated tools (vision, generation, web search, browser) without heavy subprocess calls
- Has rich panel simulation (memory, tools, swarm status, evidence)
- Has provider/model selection with lists and keyboard navigation
- Has pause/resume/stop controls for the swarm

## When to Use

Use this skill when:
- User wants the terminal/TUI to have Hermes-like features (memory, tools, proactivity, vision, generation, web, rich tool calling)
- User wants continuous looping swarm of agents with evidence and self-evolution
- User corrects the approach multiple times ("use the binary", "in looping", "enxame de agents", "looping pensativo", "faca todos sem parar", "implemente de verdade")
- You are evolving a project like simplicio-runtime's `terminal_chat.rs` and `tui_app.rs`
- You need to make a runtime have full Hermes Agent parity

Do not use for:
- One-off task execution without persistence or looping
- Pure memory updates (use the memory tool instead)
- Protected or bundled skills (do not edit hermes-agent directly for this class)

## Workflow (Mandatory Sequence)

1. **Review previous implementations** — load `hermes-agent`, `hermes-agent-skill-authoring`, `skill-library-umbrella-consolidation`, and any previously created swarm or TUI skills. Patch the most relevant one first.
2. **Use the binary** — always prefer `./target/release/simplicio agents delegate`, `simplicio run`, `simplicio runtime map` over direct edits. Direct `patch`/`write_file` on the repo is a last resort and must be followed by a runtime surface.
3. **Force continuous loop mode** — set `continuous_loop_mode = true`, `swarm_active = true` by default. Add `SwarmState` enum with Running/Paused/Stopped. Add commands `/swarm status`, `/swarm pause`, `/swarm resume`, `/swarm stop`.
4. **Auto-start swarm supervisor** — on `TerminalChat::new()`, spawn a background thread or Tokio task that periodically calls `agents delegate` with high agent count (64+). Include goal that references "Hermes parity", "continuous evolution", "thoughtful looping".
5. **Implement rich tool calling** — every command prints `[TOOL CALL START]` with JSON structure, loading state, and `[TOOL CALL END]` with formatted result. Use colors (`\x1b[36m`, `\x1b[33m`, `\x1b[32m`).
6. **Add real tool integration** — `/vision`, `/generate image|video`, `/web`, `/browse`, `/vector` must call real `hermes` CLI commands (`hermes vision_analyze`, `hermes image_generate`, `hermes video_generate`, `hermes web_search`, `hermes web_extract`).
7. **Add real vector memory** — use SQLite database (`vector_memory.db`) with table for key, embedding (BLOB), content, timestamp. Implement `/vector <query>` that returns recent semantically relevant entries.
8. **Add proactivity** — every 5 turns or on empty input, output a proactive suggestion ("Sugestão proativa: ..."). The system prompt must explicitly say the agent takes initiative and suggests next steps without being asked.
9. **Add provider/model lists** — `/provider` and `/model` must show numbered or bulleted lists and allow selection by number or name. Update onboarding to use the same list instead of free text input.
10. **Simulate rich TUI panels** — maintain a `panels` HashMap with keys for "memory", "tools", "swarm", "evidence" and return formatted panel output on `/panels` or in status.
11. **Update system prompt** — the initial system message must list all the Hermes strengths and state that the agent has surpassed previous versions in creative reasoning, broad knowledge, natural conversation, integrated tools, and intelligent proactivity.
12. **Test and commit** — add a test that verifies swarm starts, proactivity triggers, tool calls succeed, vector memory works. Commit with clear message referencing the points improved. Push to main.
13. **Verify release** — bump version in `Cargo.toml`, update CHANGELOG.md, rebuild with `cargo build --release`, create tag, push tag.

## Absorbed subclasses

This umbrella subsumes several narrower classes that should not live as separate top-level skills:
- **TUI parity evolution** — making a runtime terminal feel Hermes-like in memory, tools, proactivity, and onboarding
- **continuous loop mode** — default swarm/loop execution when the user signals "stop asking and finish"
- **runtime-first evolutionary operation** — using the external runtime as the execution engine for long-lived improvement loops

Treat those as labeled subsections of this one umbrella, not as separate discovery targets.

## Common Pitfalls

1. **Using `simplicio run` for continuous work** — it creates finite skeletons. Use `agents delegate` or a dedicated supervisor thread for true looping.
2. **Direct edits without using the binary** — violates the project's AGENTS.md. Always prefer runtime surfaces; only edit `terminal_chat.rs` when the TUI layer is the right place.
3. **Forgetting to call `start_continuous_swarm_loop()` in `new()`** — the swarm must start automatically when the TUI loads.
4. **Using subprocess calls when native integration is possible** — prefer direct Rust calls or MCP where available; CLI calls are acceptable only as a bridge.
5. **Not updating the system prompt** — the initial message must explicitly list the 5 strengths and state that the agent has surpassed previous versions.
6. **Not handling pause/resume/stop** — the swarm must respect `SwarmState` and not run when paused or stopped.
7. **Not adding proactive suggestions** — the agent must suggest next steps without being asked, especially on empty input or every N turns.
8. **Not rebuilding the binary** — changes to `terminal_chat.rs` require `cargo build --release` to appear in the running TUI.
9. **Ignoring merge conflicts after many edits** — always run `git pull --rebase` or `git reset --hard origin/main` + `git clean -fd` before major changes.
10. **Not testing** — always add a test that verifies swarm starts, proactivity triggers, tool calls succeed, vector memory works.

## Verification Checklist

- [ ] `continuous_loop_mode` and `swarm_active` default to `true`
- [ ] `TerminalChat::new()` calls `start_continuous_swarm_loop()`
- [ ] `/run` and initialization call `agents delegate` with high agent count
- [ ] `/provider` and `/model` show lists and allow selection by number or name
- [ ] `/vision`, `/generate`, `/web`, `/browse`, `/vector` call real tools and return formatted results
- [ ] Tool calls print JSON-like structure with loading and result
- [ ] Proactive suggestions appear without being asked
- [ ] Vector memory uses real SQLite table and inserts on user messages
- [ ] `/swarm status`, pause, resume, stop all work
- [ ] System prompt lists all 5 strengths and states superiority
- [ ] Test `full_hermes_with_all_features` passes
- [ ] `cargo build --release` succeeds
- [ ] Commit message references the 5 points and "Full Hermes parity"
- [ ] Pushed to main and tag created for new version

## Support Files

- `references/hermes-parity-gap-analysis.md` — detailed review of the 8 points and how each was addressed
- `references/simplicio-recent-closed-issues-summary.md` — mapping of the last 30 closed issues to our changes
- `scripts/start-swarm-supervisor.sh` — helper to launch the TUI with swarm active

Use these files when the skill is loaded.

## One-Shot Recipes

**Start full Hermes swarm:**
```bash
cd ~/Projetos/ai/simplicio-runtime
cargo build --release
./target/release/simplicio
# Type /swarm status to verify
```

**Test rich tool calling:**
```
/web "latest AI research on multi-agent systems"
/vision latest-screenshot.png
/generate image "a futuristic terminal interface with swarm status panels"
/vector "continuous evolutionary looping"
```

**Proactive test:**
Leave input empty or type `/proactive` — it should suggest next steps without being asked.

This skill replaces all previous narrow TUI, swarm, and Hermes-parity skills. Previous narrow skills have been archived under `.archive/`. Use this umbrella for all future TUI/swarm/Hermes-parity work.
