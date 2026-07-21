# Runtime-supervised agent benchmark (issue #23)

`scripts/benchmark_agents.py` is the executable contract for comparing
Simplicio Agent, Hermes Agent, Hermes Turbo Agent, and OpenClaw. It accepts
operator-provided commands in a versioned JSON manifest and prefixes every
agent invocation with the configured Simplicio Runtime command. There is no
native-command bypass in the harness.

## Setup

Copy `bench/agents/manifest.v1.example.json`, then replace the four adapter
commands with commands available in the same isolated environment. Keep the
provider, model, task suite, permissions, and runtime configuration identical
for all four agents. Do not put API keys or session keys in the manifest.

Validate without executing agents:

```bash
python scripts/benchmark_agents.py \
  --manifest bench/agents/manifest.v1.example.json \
  --validate-only
```

Capture a report and per-run JSONL receipts:

```bash
python scripts/benchmark_agents.py \
  --manifest bench/agents/manifest.v1.example.json \
  --output artifacts/agent-benchmark.json \
  --jsonl-out artifacts/agent-benchmark.jsonl
```

The command exits non-zero until a complete measured report and a baseline are
available. A baseline is supplied explicitly with `--baseline`; the harness
never overwrites or invents one.

## Event protocol

Each adapter must write one JSON object per line to stdout. Optional ordinary
text is ignored, but it cannot satisfy a metric. The supported events are:

| Event | Required field | Metric |
| --- | --- | --- |
| `startup_ready` | `elapsed_ms` | startup/prewarm |
| `ttft` | `elapsed_ms` | time-to-first-token |
| `roundtrip` | `duration_ms` | tool-loop roundtrip |
| `watcher_gate` | `duration_ms` | F3 watcher gate budget |
| `kernel_bindings` | `duration_ms` | F2 kernel binding budget |
| `handles_lazy` | `duration_ms` | F4 handles/lazy budget |
| `task_complete` | `tokens`, `tokenizer` | tokens per task |

`task_ms` is measured by the harness around the runtime-supervised process.
Token counts are accepted only when the event tokenizer exactly matches the
manifest label (`runtime#2775` in the example). Missing or mismatched values
are represented as `{ "value": null, "reason": "..." }` and block the gate.

The report uses nearest-rank p95 over non-warmup best-of-N samples. A budget
overrun or missing stage metric blocks. Baseline comparison also blocks on a
missing row, null value, or latency regression beyond the configured tolerance.

## Evidence boundary

The committed example is configuration, not benchmark evidence. Real
cross-agent measurements require the private/hosted runtime and all four
configured adapters. Until those prerequisites are present, reports must stay
`unverified` and must not claim TTFT, roundtrip, token savings, or a winner.
