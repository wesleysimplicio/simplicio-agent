# Runtime CLI/MCP parity slice

Issue #97 is intentionally bounded. The authority is
[`fixtures/capabilities/runtime-mcp-parity.v1.json`](../fixtures/capabilities/runtime-mcp-parity.v1.json),
validated by `hermes_cli.runtime_mcp_matrix.CapabilityMatrix`.

The matrix has three deterministic routes:

- `mcp`: use the named native Runtime MCP tool;
- `cli_fallback`: use the exact Runtime CLI command recorded in the row;
- `gap`: neither route is proven for that capability.

Routing always checks the declared MCP tool first, then the declared CLI
fallback. It does not infer coverage from naming conventions, health scores,
or the existence of an unrelated tool.

## Evidence boundary

The checked-in matrix currently contains only snapshot evidence:

- `cli_help` is the checked-in command-surface snapshot for Runtime 3.5.0;
- `mcp_doctor` is the checked-in record of the local `simplicio doctor --json`
  MCP-host registration (`simplicio_map`, `simplicio_memory`, and
  `simplicio_edit`).

These are not a live `tools/list` probe. A future live probe must be labelled
`kind: live` and must update the fixture deliberately. The regression tests
fail if a known command or tool disappears from an observed snapshot or if a
known command loses its matrix row.

The 9 `cli_fallback` rows are real parity gaps in the typed MCP surface, but
they are not inaccessible: the CLI route is the currently proven path. There
are no `gap` rows in this bounded fixture. That is an observed result, not a
claim that the full Runtime surface has MCP parity.

`mcp_serve.py` is a separate Simplicio Agent messaging MCP server. Its
conversation, browser, computer-use, and low-frequency bridge tools are not
counted as native Runtime MCP tools in this matrix; treating them as aliases
would invent parity.

To inspect the authority and route a command locally:

```python
from hermes_cli.runtime_mcp_matrix import load_capability_matrix

matrix = load_capability_matrix()
print(matrix.status().as_dict())
print(matrix.route("plan"))
```
