# Issue #348 E2E slice

This fixture-driven path exercises the available agent/runtime boundaries:

`issue fixture -> TaskEnvelope orientation -> plan artifact -> checkpoint ->
SimplicioTransport mechanical edit -> focused pytest -> independent requery ->
evidence receipts -> ledger delivery -> verified close`.

The copied workspace under `tests/fixtures/e2e/issue-348/workspace` is the only
workspace mutated by the test. The deterministic MCP fallback callback uses the
same operation-shaped boundary as `SimplicioTransport`; the test also covers
these typed outcomes:

| Scenario | Expected receipt | Meaning |
| --- | --- | --- |
| unavailable | `cli_unavailable` then MCP fallback | CLI cannot be resolved |
| permission | `cli_command_failed` | command ran but the action was denied |
| timeout | `cli_timeout`, retryable | command exceeded the configured deadline |
| invalid | `cli_invalid_json` | tool returned a malformed response |
| invalid tool | pipeline `error` receipt | executor rejected an unknown tool |

Measured locally by the focused pytest run: the fixture reaches `closed` only
after the focused test passes, the independent file requery matches the planned
write, all lifecycle steps have receipts, failure receipts retain their typed
codes, blocked resume replay is deduplicated, and concurrent transport calls
produce distinct request IDs.

Unverified by this slice: a live external Simplicio runtime binary, a production
mapper result, a real MCP server, the autonomous loop, external issue/PR APIs,
and CI-host behavior. Those require an integration environment beyond the
deterministic fixture harness.
