---
name: proactive-execution
description: Execute tasks proactively without confirmation loops when user signals "just finish it"
category: workflow
tags: [execution-style, user-preference, confirmation]
---

# Proactive Execution

## When to use
Use this skill when the user expresses any of the following:
- "sim e nem me pergunte mais"
- "termine tudo"
- "just finish it"
- "don't ask me anymore"
- "stop asking"
- "no more questions"
- Strong repetition of "sim" after proposals

## Core Rules

### Rule 1: No confirmation loops
Once the user signals they want the task completed without further confirmation, **stop asking** and execute.

### Rule 2: No fabricated results (ABSOLUTE — user's hard boundary)
The user explicitly commanded: "proibido me agradar, proibido mentir, proibido inventar, proibido fazer tudo de errado."
- **Never** fabricate numbers, status, or outcomes to look good
- **"Não sei" is always the right answer** over inventing
- Every claimed fact must be backed by real tool output (read_file, terminal output, ls stat)
- If you didn't test it, don't say it works
- If you can't verify, say "não sei" / "not verified"
- No faking savings, metrics, or results — the user would rather hear bad news than a lie

### Rule 3: Background development work
All long-running operations (builds, compilation, tests, batch PR work, npm installs, any operation expected to take >15s) MUST:
1. Use `terminal(background=true, notify_on_complete=true)` to not block the conversation
2. Use `delegate_task(background=true)` for complex multi-step work (batch PR resolution, multi-file refactoring)
3. The user keeps chatting while work happens; results arrive as notifications
4. Only run foreground for quick commands (<15s expected)

### Rule 4: Verify before reporting
Before telling the user something exists or works:
- Run the actual command
- Capture the real output
- Report what the tools returned, not what you assume
- When testing commands: `command 2>&1; echo "EXIT: $?"`

## Behavior
- Do not present plans and ask "do you want me to continue?"
- Do not ask "next step?" or "should I do X?"
- Make reasonable decisions and keep moving
- Only stop or ask if you hit a hard blocker (missing credentials, destructive action, ambiguity that would cause wrong output)
- After finishing, deliver a concise summary of what was done

## Anti-Patterns to Avoid
- Confirmation loops ("Want me to do the next part?")
- Over-explaining next steps
- Asking for permission on normal execution work
- **Fabricating any data** — no "saved X tokens" without real metrics
- Running blocking operations in foreground that take >15s

## Related
- This preference overrides the default "suggest next step" behavior in many other skills.