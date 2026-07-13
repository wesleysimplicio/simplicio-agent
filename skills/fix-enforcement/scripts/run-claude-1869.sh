#!/bin/bash
set -e
REPO=/Users/wesleysimplicio/simplicio-runtime
TASK=$(cat "$REPO/.claude-task.md")
"$HOME/.nvm/versions/node/v24.15.0/bin/claude" -p "$TASK" --allowedTools Read,Edit,Write,Bash --max-turns 30 --dangerously-skip-permissions 2>&1
echo "EXIT_CODE: $?"
