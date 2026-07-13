#!/bin/bash
echo "=== PLUGIN INIT CHECK ==="
cat ~/.hermes/plugins/simplicio/__init__.py | head -20
echo "=== GREP HOOK ==="
grep -n "register_hook\|DISABLED\|pre_tool" ~/.hermes/plugins/simplicio/__init__.py
echo "=== PLUGIN TOOLS CHECK ==="
cat ~/.hermes/plugins/simplicio/tools.py | head -20
echo "=== SIMPLICIO BINARY ==="
which simplicio
simplicio --version 2>/dev/null
ls -la ~/.local/bin/simplicio 2>/dev/null
ls -la ~/.cargo/bin/simplicio 2>/dev/null
echo "=== SIMPLICIO PLUGIN DIR ==="
ls -la ~/.hermes/plugins/simplicio/
echo "=== ENFORCEMENT ENV ==="
echo "SIMPLICIO_ENFORCEMENT=$SIMPLICIO_ENFORCEMENT"
