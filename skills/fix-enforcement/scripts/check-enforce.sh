#!/bin/bash
echo "=== register_hook ==="
grep -n 'register_hook' /Users/wesleysimplicio/.simplicio_agent/plugins/simplicio/__init__.py
echo "=== DISABLED ==="
grep -n 'DISABLED' /Users/wesleysimplicio/.simplicio_agent/plugins/simplicio/__init__.py
