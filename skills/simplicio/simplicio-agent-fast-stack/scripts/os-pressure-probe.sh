#!/usr/bin/env bash
# macOS pressure snapshot for Simplicio stack troubleshooting.
set -euo pipefail
echo "=== Hardware ==="
sysctl -n hw.memsize hw.ncpu 2>/dev/null | awk 'NR==1{printf "RAM_bytes=%s\n",$0} NR==2{printf "ncpu=%s\n",$0}'
echo "=== Swap ==="
sysctl vm.swapusage 2>/dev/null || true
memory_pressure 2>/dev/null | grep -E 'free percentage|Swap' || true
echo "=== Load / mem (top) ==="
top -l 1 -n 0 2>/dev/null | egrep 'Load Avg|PhysMem|CPU usage' || true
echo "=== Simplicio-related processes ==="
ps aux 2>/dev/null | egrep 'llama-server|cargo build|rustc --crate-name simplicio|hermes_cli.main gateway' | grep -v grep || echo "(none)"
echo "=== LaunchAgents (simplicio/hermes/llama) ==="
launchctl list 2>/dev/null | awk '$3 ~ /simplicio|hermes.gateway|llama|runtime.watch/ {print}' || true
echo "=== Top CPU (5) ==="
ps aux -r 2>/dev/null | head -6 | tail -5 || true