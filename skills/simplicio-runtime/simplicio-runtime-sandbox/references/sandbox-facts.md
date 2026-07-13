# Simplicio Runtime — Edit/Read Sandbox: verified facts & transcripts

Gathered 2026-07 from `simplicio-runtime` source + live tests on this host.

## Source locations
- Sandbox enforcement (MCP only): `src/main_parts/chunk_08.rs`
  - `mcp_edit_sandbox(repo, plan)` — lines 4139-4168. Normalizes path lexically (`mcp_normalize_path`, 4121-4134, resolves `.`/`..` without touching fs), then `if norm.starts_with(&root_norm) { Ok(()) } else { Err("simplicio_edit: sandbox — file {file:?} escapes the workspace root {root_norm:?}") }`.
  - Invoked from MCP dispatch: `"simplicio_edit" =>` (line 3942-3948) and `"simplicio_read"` (line 3906-3911, reuses `mcp_edit_sandbox` on the plan).
  - Read counterpart `mcp_read_sandbox(repo, file)` — lines 4173-4196, same logic, error `simplicio_file_read: sandbox — path ... escapes the workspace root`.
  - Issue tag in source comment: `#2674 sandbox`.
- CLI edit path (NO sandbox): `src/anti_fake_remediation.rs`
  - `RemediationExecutor::apply_plan` (line 483): `let abs_path = self.repo_root.join(&plan.file);` then reads/writes. No escape check — absolute path outside repo is honored.
  - Note: this executor is the *remediation* path; the primary `simplicio edit` MCP entry also routes through `mcp_edit_sandbox` before invoking the CLI. The sandbox is a property of the **MCP dispatch layer**, not the underlying edit engine.

## Live test transcripts (this host)
Runtime binary: `/Users/wesleysimplicio/.local/bin/simplicio` (Simplicio Runtime 3.4.0).
Repo root for tests: `/Users/wesleysimplicio/Projetos/ai/simplicio-agent`.

### MCP — BLOCKED
```
mcp_simplicio_simplicio_edit plan={"file":"/tmp/simplicio_outside_test.txt","operations":[{"op":"create","text":"teste de escrita fora do repo"}]}
→ error: "simplicio_edit: sandbox — file \"/tmp/simplicio_outside_test.txt\" escapes the workspace root \"/Users/wesleysimplicio/Projetos/ai/simplicio-agent\""
```

### CLI — WRITES OK
```
cd /Users/wesleysimplicio/Projetos/ai/simplicio-agent
simplicio edit '{"file":"/tmp/cli_outside_test.txt","operations":[{"op":"create","text":"teste cli fora do repo"}]}' --json
→ {"schema":"simplicio.edit-result/v1","status":"ok","file":"/tmp/cli_outside_test.txt","created":true,...,"bytes_after":22,...}
```
Cleanup: `rm -f /tmp/cli_outside_test.txt /tmp/simplicio_outside_test.txt`.

## Practical takeaways
- To drop a generated artifact in `~` or `/tmp` via Simplicio: call `simplicio edit` from a `terminal` step, not the `mcp_simplicio_simplicio_edit` tool.
- The sandbox protects the **host repo from a coaxed MCP client** (#2674) — it is a security boundary on the MCP surface, not a general runtime limitation.
- Neural memory entry captured this as fact id 37985 ("Simplicio edit sandbox: MCP sim, CLI não").
