# Native benchmark fixture slice

`bench/fixtures/manifest.json` is the versioned `simplicio.bench-fixture/v1`
corpus for Native token and latency gates. It contains 40 scrubbed cases in
eight route categories (`L0` through `L3`), with five cases per category and
weights summing to 100. Each case ID is `sha256:` plus the digest of its
canonical `category`, `input`, and `expected` fields; changing a case therefore
requires an intentional fixture-address update.

The corpus is a deterministic proxy for this bounded slice. Its sampling note
records the source shapes and date, but marks receipt-derived representativeness
as `UNVERIFIED|` because no scrubbed SessionDB sample was available in this
checkout. Native gates can adopt the same schema and replace the provisional
weights when receipt mining lands.

## Offline stub report

The harness has no runtime or provider dependency and makes no network calls:

```text
python -m bench.harness run --fixtures bench/fixtures/manifest.json \
  --provider stub --repeats 100 --warmup 5 --json out/bench-report.json
```

The report uses `simplicio.bench-report/v1` and includes the exact fixture
SHA-256, token counts, p50/p95 local latency, per-stage timings, and peak
`tracemalloc` memory by category. Token counts use the documented portable
UTF-8-bytes/4 ceiling proxy; latency is `MEASURED|` for local stub execution,
not a claim about a remote model. The report's `fixture_sha256` and stable
category/route fields are the handoff boundary for Native token/latency gates.
