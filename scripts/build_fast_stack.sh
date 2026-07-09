#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
VENV_PY="${VENV_PY:-.venv/bin/python}"
if [ ! -x "$VENV_PY" ]; then
  echo "venv python not found at $VENV_PY" >&2
  exit 1
fi
"$VENV_PY" -m pip install -q maturin tiktoken h2
( cd rust_ext && "../$VENV_PY" -m maturin develop )
"$VENV_PY" -c "from agent._hermes_fast import HAVE_RUST; import importlib.util as u
for m in ['orjson','msgspec','uvloop','tiktoken','h2','hermes_fast']:
 print(m, 'ON' if u.find_spec(m) else 'OFF')
print('HAVE_RUST', HAVE_RUST); assert HAVE_RUST"
echo DONE
