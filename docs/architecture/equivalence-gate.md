# Equivalence gate and fail-closed canary (issue #340)

`tools/equivalence_gate.py` is the bounded, offline boundary for comparing a
new path with its legacy shadow run.  Each `simplicio.shadow-report/v1` row
contains a `fixture_id`, `category`, and `baseline`/`candidate` objects with
these dimensions:

```json
{
  "behavior": {"effect_request": {}, "output": "..."},
  "tokens": 100,
  "latency": {"p95": 10.0},
  "memory": {"peak_memory_bytes": 1024},
  "receipts": {"schema": "simplicio.effect-receipt/v1", "required_fields": ["id"]}
}
```

The default tolerances are behavior `0%`, tokens `0%`, latency p95 `+10%`,
memory `+10%`, and receipts `0%`; every dimension is blocking by default.
Behavior compares normalized EffectRequest/output JSON.  Numeric dimensions
use `(candidate - baseline) / baseline`, so a zero baseline plus a non-zero
candidate is an infinite regression.  Receipt comparison is intentionally
limited to schema and required fields.  A dimension may be configured as an
`observation`, which yields `hold` instead of `reject`; an all-green matrix
yields `promote`.

`FeatureFlagStore` persists `native.slice.<name>` flags beneath a state root.
An enabled value is valid only inside an exact profile and exact session pin.
Missing files, malformed JSON, invalid schemas, I/O errors, unknown profiles,
and unknown sessions all return `False` (legacy path).  The store never uses
default-on behavior.  `CanaryController` writes a transition event for every
activation and rollback; divergence above the supplied threshold automatically
turns the pinned session off.

This slice compares supplied reports only.  Its result is marked
`UNVERIFIED|offline comparison of supplied shadow reports`; production
shadow-run generation, promotion/update wiring, and live evidence remain
outside this boundary.
