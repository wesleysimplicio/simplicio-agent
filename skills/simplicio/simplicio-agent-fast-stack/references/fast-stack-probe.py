#!/usr/bin/env python3
"""Fast-stack verification probe for Simplicio Agent (PR #104 performance modules).
Run from the repo root with the venv python:
    .venv/bin/python references/fast-stack-probe.py
Reports which perf layers are actually ON, whether config is kept out of the boot path,
and a real json hot-path micro-bench (orjson vs stdlib). Does NOT need an upstream checkout.
"""
import importlib.util as u
import time, json, orjson

print("=== Fast-stack layer availability ===")
layers = ['orjson', 'msgspec', 'uvloop', 'tiktoken', 'h2', 'hermes_fast']
all_on = True
for m in layers:
    on = bool(u.find_spec(m))
    all_on &= on
    print(f"  {m:14s}: {'ON ' if on else 'OFF'}")

try:
    from agent._hermes_fast import HAVE_RUST
    print(f"  HAVE_RUST      : {HAVE_RUST}")
except Exception as e:
    print(f"  HAVE_RUST      : ERROR {e}")
    HAVE_RUST = False

print("\n=== Boot-slim check (config must NOT be a top-level import in hermes_cli/main.py) ===")
import subprocess, sys
# cheap static check
main_src = open("hermes_cli/main.py", encoding="utf-8").read()
toplevel_config = any(
    ln.startswith(("import hermes_cli.config", "from hermes_cli.config import"))
    and "subcommands" not in ln
    for ln in main_src.splitlines()
)
print(f"  hermes_cli.config at boot top-level: {'YES (bad)' if toplevel_config else 'no (good)'}")

print("\n=== json hot-path micro-bench (tool-result shape) ===")
payload = {"a": [1, 2, 3], "b": "tool result" * 50}
N = 20000
t0 = time.perf_counter()
for _ in range(N):
    orjson.dumps(payload)
oj = (time.perf_counter() - t0) / N * 1e6
t0 = time.perf_counter()
for _ in range(N):
    json.dumps(payload)
pj = (time.perf_counter() - t0) / N * 1e6
print(f"  orjson: {oj:.2f} us   stdlib: {pj:.2f} us   speedup: {pj/oj:.1f}x")

print("\n=== Verdict ===")
if all_on and HAVE_RUST and not toplevel_config:
    print("  FAST STACK FULLY ON — no pure-Python fallback active.")
elif not HAVE_RUST:
    print("  hermes_fast MISSING — build rust_ext (cd rust_ext && python -m maturin develop).")
else:
    print("  Partial — install missing layers: pip install tiktoken h2 && build rust_ext.")
