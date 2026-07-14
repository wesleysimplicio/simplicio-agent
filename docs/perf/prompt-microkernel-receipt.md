# Prompt microkernel integration receipt

`tools/prompt_microkernel_integration_receipt.py` is the bounded Issue #220
checker for the existing lazy prompt microkernel. Run it from the repository
root:

```bash
python tools/prompt_microkernel_integration_receipt.py --json
```

The command executes three stages independently:

- `SOURCE` hashes `agent/prompt_microkernel.py` from the selected checkout.
- `LOADED` imports `agent.prompt_microkernel` and verifies that the loaded
  module resolves to that source file.
- `CALLED` invokes `CapabilityBroker.expand_with_receipt("act")`, checks the
  returned schema and deterministic expansion receipt, and records its schema
  hash.

Passing these stages proves only that this checkout contains, loads, and calls
the broker path. The receipt marks `PACKAGED`, `DEFAULT`, and `E2E` as
`UNVERIFIED` because it does not build/install a wheel, trace a default product
entry point, or run a provider-backed conversation. It also makes no latency,
throughput, token, CPU, or memory claim; those require a separate benchmark
with raw samples and a same-environment baseline.
