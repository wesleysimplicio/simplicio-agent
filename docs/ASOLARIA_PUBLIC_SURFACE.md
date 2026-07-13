# Asolaria public surface (issue #125)

This repository now exposes the existing deterministic Asolaria implementations
through `simplicio_agent.asolaria`:

```bash
python -c "from simplicio_agent import asolaria; assert asolaria.run_n_nest().subtree_ok"
python -m simplicio_agent.asolaria --selftest
```

The facade delegates to the current skill-owned modules:

- `skills/asolaria-patterns/lib/nest_depthn.py` — N-Nest corrective gate;
- `skills/asolaria-patterns/lib/prism_comb.py` — PRISM-COMB round-trip and CRT
  capacity gate.

The focused tests cover importability, clean/tampered N-Nest behavior,
PRISM-COMB round trips, the explicit CRT `held` result, and the public
selftest API; the module selftest entrypoint was also run directly.

## Deliberate boundary

This is a source-checkout integration slice. The facade loads the skill modules
from the repository and raises a clear error if those files are unavailable;
packaging the skill-owned implementations is a separate follow-up.

Nothing here proves that the Rust `simplicio-runtime` consumes these Python
modules, shares their vectors, or has a cross-repository integration test. That
dependency/gap remains open and must be addressed in `simplicio-runtime` before
issue #125 can honestly claim runtime cross-repo validation.
