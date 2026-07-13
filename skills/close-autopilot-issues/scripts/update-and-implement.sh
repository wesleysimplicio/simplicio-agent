#!/bin/bash
REPO=wesleysimplicio/simplicio-runtime
DIR=/Users/wesleysimplicio/simplicio-runtime

echo "=== 1. Updating issue details ==="

# Update #1869 - Tool use no loop
gh api -X PATCH repos/$REPO/issues/1869 -f title="Runtime Agentic Chat: tool use no loop" -f body="Add tool use to chat" 2>/dev/null || \
printf '{"title":"Runtime Chat tool use","body":"Tool binding: shell, edit, run, memory"}' | gh api -X PATCH repos/$REPO/issues/1869 --input -

# Update #1870
gh api -X PATCH repos/$REPO/issues/1870 -f title="Agentic Chat REPL routing" -f body="REPL and Discord Telegram routing" 2>/dev/null || \
printf '{"title":"Chat REPL routing","body":"REPL mode and multi-platform routing"}' | gh api -X PATCH repos/$REPO/issues/1870 --input -

# Update #1871
gh api -X PATCH repos/$REPO/issues/1871 -f title="Agentic Chat subagent delegation" -f body="Improved agents delegate" 2>/dev/null || \
printf '{"title":"Chat delegation","body":"Subagent delegation with isolation"}' | gh api -X PATCH repos/$REPO/issues/1871 --input -

echo "=== 2. Starting implementation ==="
cd $DIR
echo "Branch: $(git branch --show-current 2>/dev/null || echo detached)"
echo "Commits: $(git log --oneline -3 2>/dev/null)"
echo "Files: $(find src/ -name '*.rs' | wc -l)"
