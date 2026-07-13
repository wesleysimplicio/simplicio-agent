#!/bin/bash
echo "=== register_hook ==="
grep -n 'register_hook\|DISABLED' /Users/wesleysimplicio/.hermes/plugins/simplicio/__init__.py 2>/dev/null
echo "=== first 10 lines ==="
head -10 /Users/wesleysimplicio/.hermes/plugins/simplicio/__init__.py 2>/dev/null
