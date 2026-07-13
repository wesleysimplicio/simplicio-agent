#!/bin/bash
set -e
PLUGIN_DIR="$HOME/.hermes/plugins/simplicio"
cp "$PLUGIN_DIR/__init__.py" "$PLUGIN_DIR/__init__.py.bak.$(date +%s)"
sed -i '' 's/ctx.register_hook("pre_tool_call"/# DISABLED: ctx.register_hook("pre_tool_call"/' "$PLUGIN_DIR/__init__.py"
echo "RESULT:"
grep -n "register_hook\|DISABLED" "$PLUGIN_DIR/__init__.py"
echo "DONE"
