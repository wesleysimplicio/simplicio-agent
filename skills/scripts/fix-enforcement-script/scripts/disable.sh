#!/bin/bash
cd ~/.hermes/plugins/simplicio
cp __init__.py __init__.py.bak
sed -i '' 's/ctx.register_hook("/# DISABLED: ctx.register_hook("/' __init__.py
echo "Enforcement disabled. Start a new session."
