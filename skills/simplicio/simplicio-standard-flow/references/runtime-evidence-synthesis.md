# Runtime evidence synthesis notes

Session focus: concise integration summary for `self-observer` + `simplicio_loop` evidence.

## Evidence anchors
- `src/agent_state_command.rs`: self-observer daemon lifecycle, status/log paths, PID liveness, structured cycle reports, watcher approval/rejection, decision recall/store.
- `src/loop_contract.rs`: native loop anchor-gate port exists; live autonomous-loop hookup and the remaining parity oracles are still deferred in this slice.
- `.simplicio/runtime-resource-map.json`: canonical loop/run-loop surfaces are already exercised/green, so the next work is integration and parity closure rather than invention.

## Reliable synthesis pattern
1. Start from code, not memory: locate the concrete implementation surface first.
2. Compress to at most three priorities.
3. For each priority, state:
   - what already exists,
   - what is missing,
   - why it matters to runtime integration.
4. Keep the final answer short and actionable; do not expand into a plan unless asked.

## Useful wording pattern
- "wired but not integrated"
- "partial parity, remaining gates deferred"
- "evidence exists, but the acceptance path is not unified yet"

## Session-specific lesson
If claims-gating or MCP lookup is slow/unavailable, continue with direct repo evidence and cite the blocker briefly rather than stalling the synthesis.