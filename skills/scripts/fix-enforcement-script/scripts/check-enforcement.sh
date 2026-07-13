#!/bin/bash
echo "=== Enforcement Plugin Status ==="
cat ~/.hermes/plugins/simplicio/__init__.py | head -5
echo "---"
grep "register_hook" ~/.hermes/plugins/simplicio/__init__.py
echo "---"
echo "=== Simplicio Binary ==="
which simplicio
simplicio --version 2>/dev/null || echo "no version"
echo "=== Simplicio-Runtime Dir ==="
ls ~/Projetos/ai/simplicio-runtime/ | head -20
echo "=== Git Status (quick) ==="
cd ~/Projetos/ai/simplicio-runtime && git log --oneline -5 2>/dev/null || echo "not a git repo or no access"
echo "=== Issues ==="
cd ~/Projetos/ai/simplicio-runtime && gh issue list --state open --limit 10 2>/dev/null || echo "gh not available"
