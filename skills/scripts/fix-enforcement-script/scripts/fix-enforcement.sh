#!/bin/bash
# Fix the Simplicio enforcement plugin
# This script edits ~/.hermes/plugins/simplicio/tools.py to:
# 1. Fix the register_tool argument schemas
# 2. Remove or disable the pre_tool_call enforcement hook

PLUGIN_DIR="$HOME/.hermes/plugins/simplicio"
TOOLS_PY="$PLUGIN_DIR/tools.py"
BACKUP="$TOOLS_PY.bak.$(date +%s)"

echo "=== Fix Enforcement Plugin ==="

# Step 1: Read the file
if [ ! -f "$TOOLS_PY" ]; then
    echo "ERROR: $TOOLS_PY not found"
    exit 1
fi

echo "Backing up to $BACKUP"
cp "$TOOLS_PY" "$BACKUP"

# Step 2: Fix using python for reliability
python3 << 'PYFIX'
import re

with open("$HOME/.hermes/plugins/simplicio/tools.py", "r") as f:
    content = f.read()

# Show what's in the file (first 50 lines)
lines = content.split("\n")
print(f"Total lines: {len(lines)}")
for i, line in enumerate(lines[:50]):
    print(f"{i+1}: {line}")

# Disable the pre_tool_call hook by commenting it out
# Pattern: look for register_hook or @hook or pre_tool_call
content = content.replace("pre_tool_call", "# DISABLED: pre_tool_call")
content = content.replace("register_hook", "# DISABLED: register_hook")

# Fix empty arguments dicts in register_tool calls
content = content.replace("arguments={}", 'arguments={"task": {"type": "string", "description": "Command or task to execute"}}')

with open("$HOME/.hermes/plugins/simplicio/tools.py", "w") as f:
    f.write(content)

print("File updated")
print("\nChanged lines:")
for i, line in enumerate(content.split("\n")):
    if "DISABLED" in line or "arguments=" in line:
        print(f"  {i+1}: {line.strip()}")
PYFIX

echo ""
echo "=== Verification ==="
python3 -m py_compile "$TOOLS_PY" && echo "Syntax: OK" || echo "Syntax: FAILED"

echo ""
echo "=== DONE ==="
