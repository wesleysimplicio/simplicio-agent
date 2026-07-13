Implement agentic tool use in the simplicio chat loop (issue #1869).

Repo: /Users/wesleysimplicio/simplicio-runtime
Branch: agent/1869-tool-use-chat (already checked out)

GOAL: Add tool-calling to `simplicio chat`. The LLM should call shell/edit/read/run during conversation.

STEPS:
1. Read CLAUDE.md, AGENTS.md, docs/INDEX.md first
2. Find the chat loop implementation in src/main.rs
3. Add a structured tool protocol: LLM can request tool calls, runtime executes and feeds results back
4. Support tools: shell, read, edit, simplicio run
5. Keep it simple - text-based protocol
6. Verify with `cargo check`

FOLLOW EXISTING PATTERNS. Minimal changes.
