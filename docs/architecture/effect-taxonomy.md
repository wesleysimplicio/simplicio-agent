# Shadow effect taxonomy

This is the closed effect vocabulary for the Native 1.2 shadow-run boundary
(issue #339). Every effect crossing the future invocation choke point must be
represented by a typed `EffectRequest`; an unrecognized value is blocked before
any callback is called. `tools/shadow_effects.py` owns the contract and the
shadow-only behavior. It does not replace `tools/transaction_primitives.py`.

| Kind | Class | Shadow behavior | Existing boundary / representative call sites |
| --- | --- | --- | --- |
| `fs_read` | filesystem read | read-through only | `tools/terminal_tool.py`, `tools/file_operations.py` |
| `fs_write` | filesystem mutation | stage in disposable overlay | `tools/terminal_tool.py`, `tools/file_operations.py` |
| `process_exec` | process execution | record and block | `tools/terminal_tool.py`, `tools/process_registry.py` |
| `network_http` | network/HTTP | sentinel records and blocks | `tools/web_tools.py`, provider HTTP clients |
| `provider_remote` | remote model/provider call | record and block | `agent/auxiliary_client.py`, provider adapters |
| `github_api` | GitHub API | record and block | `tools/github_tools.py`, `hermes_cli/` integrations |
| `platform_message` | outbound platform message | record and block | `tools/send_message_tool.py`, `gateway/platforms/` |
| `state_write` | agent state-root write | record and block | `hermes_state.py`, session/receipt writers |

## Contract

`EffectRequest` contains the effect kind, operation, target, JSON payload, and
an optional read-through marker. Its request ID is a stable SHA-256 of those
fields. `EffectInterceptor` records every typed request, serves `fs_read` only
through an explicit callback, stages `fs_write` under `ShadowOverlay`, and
blocks all other effects. Unknown or malformed input returns a blocked decision
and cannot execute a callback. `NetworkSentinel` records attempted outbound
effects, while `FilesystemSentinel` compares before/after snapshot roots using
the existing read-only snapshot primitive.

`compare_effect_sequences()` emits `simplicio.shadow-report/v1` and detects
extra, missing, reordered, and payload-divergent requests. `ShadowReceipt`
binds the snapshot digest, report digest, sentinel evidence, and pass/fail
verdict in an HBP-compatible envelope (`simplicio.hbp-receipt/v1`). A passing
receipt is rejected unless effect sequences are equivalent and both sentinels
pass.

## Choke-point decision and gaps

Issue #334/#228 remains open, so the repository-wide single invocation choke
point has not yet been selected. This slice therefore provides a real,
standalone contract with focused tests but intentionally does not modify tool,
gateway, provider, release, namespace, or snapshot call sites. Until #228 is
resolved, no claim is made that every production effect is intercepted.

The overlay is disposable and never commits to a host tree. Network blocking
is represented by a deterministic sentinel record; an OS proxy/namespace is a
future system-integration gate. Full fixture execution and benchmark evidence
remain dependent on the choke point and the runtime/supervisor integration.
