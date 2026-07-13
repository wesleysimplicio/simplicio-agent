#!/usr/bin/env bash
# Build & activate the Simplicio Agent fast stack on a SOURCE CHECKOUT.
# Run from the repo root:  bash scripts/build_fast_stack.sh
# The Rust hot-path (hermes_fast) is NOT installed by pip — it must be built with maturin.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# When this script lives under ~/.simplicio_agent/skills/.../scripts/, set:
#   REPO_ROOT=/path/to/simplicio-agent bash scripts/build_fast_stack.sh
if [ ! -f "$REPO_ROOT/rust_ext/Cargo.toml" ]; then
  echo "rust_ext not found under $REPO_ROOT; set REPO_ROOT to simplicio-agent checkout" >&2
  exit 1
fi
cd "$REPO_ROOT"

VENV_PY="${VENV_PY:-.venv/bin/python}"
if [ ! -x "$VENV_PY" ]; then
  echo "venv python not found at $VENV_PY; set VENV_PY=/path/to/python" >&2
  exit 1
fi

echo "==> installing maturin + tiktoken + h2"
"$VENV_PY" -m pip install maturin tiktoken h2

echo "==> building rust_ext (hermes_fast) into the venv"
( cd rust_ext && ../"$VENV_PY" -m maturin develop )

echo "==> verifying"
"$VENV_PY" - <<'PY'
from agent._hermes_fast import HAVE_RUST
import importlib.util as u
for m in ['orjson','msgspec','uvloop','tiktoken','h2','hermes_fast']:
    print(f"  {m}: {'ON' if u.find_spec(m) else 'OFF'}")
print("  HAVE_RUST:", HAVE_RUST)
if not HAVE_RUST:
    raise SystemExit(1)
PY
echo "DONE. hermes_fast active; agent no longer on pure-Python fallback."
