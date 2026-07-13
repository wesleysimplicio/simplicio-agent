# Asolaria Porting Notes (session-derived)

## Latest pass: `asolaria-patterns` skill (4 deterministic primitives)
| Pattern | Source repo | Module | Evidence |
|---------|-------------|--------|----------|
| N-Nest cosign | N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED | nest_cosign.py | tamper caught R.1.2.0, 40 cosign links |
| HRM planner | HRM/models/hrm/hrm_act_v1.py | hierarchical_planner.py | 2 replans, seq H L L L H L L L |
| BEHCS supervisor | asolaria-behcs-256/tools/behcs | behcs_supervisor.py | gc_cap=5, mistake exhaust=1 |
| Wormhole bridge | simplicio-runtime/asolaria/wormhole_bridge.rs | wormhole_bridge.py | tamper rejected, chain_links=3 |

The skill lives at `~/.simplicio_agent/skills/asolaria-patterns/`. Wrapper
`simplicio-asolaria` (`~/.local/bin`) runs all four `--selftest`s + pytest.
Evidence: 11/11 pytest PASS.

## Tool-usage facts (durable)
- `simplicio-agent` repo is MANAGED: native write_file/patch blocked. Use
  `simplicio edit --plan <file.json> --repo <path>`.
- Plan op field is `text` (not `content`). A `content` plan validates but no-ops.
- MCP `mcp_simplicio_simplicio_edit` wants inline JSON string, not a path.
- `mcp_simplicio_simplicio_exec` blocks pipes / `>`; use terminal for pipelines.
- Installed `simplicio` binary is v3.4.0 and lacks an exposed `wormhole`
  subcommand (falls through to `compat`). The runtime source already has
  `wormhole_command` + `ReceiptChain`. Rebuild pending (working tree dirty,
  llama.cpp build is heavy).

## Repos cloned this session (under /Users/wesleysimplicio/Projetos/ai/)
- asolaria-behcs-256
- HRM
- N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED

## Earlier pass notes (sanitizer / session synthesis)
- Sanitizer: real regex redaction, count redactions, hard char cap, typed wrapper.
- Session synthesis: deterministic markdown page with counts, first/last signal,
  bounded highlight set. Prefer deterministic over LLM unless semantic compression
  is genuinely needed.
- Keep porting local to the module being changed before widening scope.

## Token savings (latest session)
- ~3.5k paid tokens saved: 6 files via `simplicio edit` vs native write_file.
- ~2k tokens saved: orient via `simplicio map` + `simplicio memory` MCP.
