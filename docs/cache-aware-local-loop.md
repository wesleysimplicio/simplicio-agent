# Cache-aware local loop slice

`agent.local_agent_loop.LocalAgentLoop` is the bounded integration seam for
the cache-aware local-agent epic. It keeps a `PromptZones` stable prefix bound
to one Runtime `InferenceLease`, then sends model-proposed JSON through the
existing `tool_call_batch` parser/classifier/executor. Only the existing
read-only classifier can enable parallel dispatch; mutations remain serial.

The turn receipt contains hashes, lease identity, call names/ids and outcome,
but never prompt or tool arguments. The receipt is local deterministic evidence
and is not a claim that the provider delivered a cache hit.

Remaining epic gaps are intentionally outside this slice: Runtime-backed
cache-hit accounting, constrained local-model grammar transport, lazy schema
loading, no-progress recovery, browser compact-state escalation, and the
reproducible evaluation lane.
