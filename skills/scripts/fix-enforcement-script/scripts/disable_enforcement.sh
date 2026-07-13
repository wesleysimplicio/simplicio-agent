#!/bin/bash
# Disable Simplicio enforcement hook
# Called by cron no_agent job
cd ~/.hermes/plugins/simplicio || exit 1
cp __init__.py __init__.py.bak 2>/dev/null
sed -i '' 's/ctx.register_hook("pre_tool_call"/# DISABLED: ctx.register_hook("pre_tool_call"/' __init__.py
echo "RESULT:"
grep "register_hook" __init__.py
