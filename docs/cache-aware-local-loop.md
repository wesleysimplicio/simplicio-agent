# Cache-aware local loop slice

`agent.local_agent_loop.LocalAgentLoop` is the bounded integration seam for
the cache-aware local-agent epic. It keeps a `PromptZones` stable prefix bound
to one Runtime `InferenceLease`, validates model-proposed JSON through the
existing grammar and `tool_call_batch` policy, and expands rare schemas only
when their calls arrive. Only the existing read-only classifier can enable
parallel dispatch; mutations remain serial.

Each turn also gates calls through `NoProgressGuard`, projects browser
`compact_state` without retaining raw snapshots, writes a content-addressed
telemetry receipt, and emits a safe `simplicio.local-agent-evaluation/v1`
record to the optional evaluation hook. The receipt contains hashes, lease
identity, call names/ids, policy decisions and outcome, but never prompt or
tool arguments. It is local deterministic evidence, not a claim that the
provider delivered a Runtime cache hit.

The focused integration test proves the local seam only. Runtime cache-hit
accounting, provider-specific local-model transport and cross-repository
evaluation remain unverified here.
