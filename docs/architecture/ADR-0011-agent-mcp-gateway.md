# ADR-0011: Simplicio Agent as the sole public MCP gateway

**Status:** Accepted (2026-07-13).  
**Owner:** @wesleysimplicio.  
**Supersedes:** Direct external-LLM registration of `simplicio serve --mcp --stdio`.  
**Depends on:** [ADR-0010](ADR-0010-runtime-first-execution.md).

## Context

External LLM hosts such as Cursor, VS Code, Gemini, Antigravity, Claude, and
Codex need one stable Simplicio integration. Publishing the Runtime MCP surface
directly makes every host understand execution details, duplicates routing, and
injects a large static tool catalog into provider prompts.

The Simplicio Agent is the reasoning and coordination boundary. The compiled
Simplicio Runtime is its private execution layer. External hosts must talk to
the Agent, not bypass it.

## Decision

`simplicio-agent mcp serve` is the **only public MCP entrypoint** for external
LLMs.

```text
Cursor / VS Code / Gemini / Antigravity / Claude / Codex
                           |
                           | MCP: natural-language intent
                           v
                    Simplicio Agent
          reasoning + coordination + contextual recall
                           |
                           | compiled CLI contracts
                           v
                    Simplicio Runtime
                  deterministic execution only
```

The Runtime MCP server may remain available temporarily for internal
compatibility and migration, but installers, product documentation, and new
client registrations MUST NOT expose it directly. It is not the public product
boundary.

## Public MCP surface

The Agent exposes a small stable facade rather than one MCP tool per Runtime
command:

- `simplicio_act(request, workdir?, client?, timeout_seconds?)` — autonomously
  completes an intent through a real Agent session;
- `simplicio_capabilities(query, workdir?, limit?)` — returns compact Helo-ranked
  capability metadata without invoking a remote LLM;
- existing messaging, browser, computer-use, approval, and low-frequency tools
  remain available for compatibility.

Most clients SHOULD call `simplicio_act` directly. Capability recall is already
performed internally; explicit discovery exists for hosts that need previews.

## Command and skill recall

The Agent MUST NOT inject the Runtime's complete command catalog into every MCP
client prompt. It asks the Runtime's Helo registry through:

```text
simplicio capabilities rank "<intent>" --repo <workdir> --json
```

Only a bounded metadata-only selection is placed in the Agent request. Skill
recall follows the same lazy-loading principle. This keeps client schemas stable
and prompt cost proportional to the task.

## Default execution profile

Every `simplicio_act` invocation uses:

```text
--yolo
mode = fast:fast
source = tool
```

`fast:fast` is a gateway profile, not a model ID:

- first `fast`: `agent.service_tier=fast`, translated by Hermes to the priority
  service tier;
- second `fast`: `agent.reasoning_effort=low`, quiet output (`-Q`), compact
  command recall, and no unnecessary catalog bodies.

The configured Agent model remains authoritative. Passing `-m fast:fast` is
forbidden because Hermes correctly rejects it as an invalid model ID.

`--yolo` is intentionally unconditional for this operator's Agent gateway. The
MCP endpoint MUST therefore remain local or authenticated. A public anonymous
transport is forbidden.

## Execution ownership

The external LLM supplies intent and retains its own conversation. The Agent
owns reasoning, coordination, capability selection, progress, and final
communication. Every executable action follows ADR-0010 through the Runtime.
Native execution is only a temporary capability-gap fallback and triggers the
mandatory parity loop.

The Agent MUST NOT register its own MCP server as a client of itself. Internal
Agent-to-Runtime communication uses the compiled CLI, avoiding recursive MCP
calls and duplicated tool schemas.

## Failure contract

The gateway is fail-closed:

- blank request -> explicit error;
- missing Runtime or Agent binary -> explicit error;
- invalid workdir -> explicit error;
- capability recall failure -> Agent may continue with a typed unavailable hint;
- Agent timeout/non-zero exit -> structured failure, never invented success;
- output is bounded and reports truncation.

## Client registration

New integrations MUST register:

```json
{
  "command": "simplicio-agent",
  "args": ["mcp", "serve"]
}
```

They MUST NOT register `simplicio serve --mcp --stdio`.

## Consequences

Positive:

- any MCP-capable LLM gets the same autonomous Agent;
- Runtime commands can evolve without changing external MCP schemas;
- command and skill recall reduce prompt tokens;
- policy, evidence, communication, and execution stay centralized;
- the Runtime remains execution-only rather than becoming a second brain.

Costs:

- synchronous `simplicio_act` occupies one MCP request for the task duration;
- long-running task handles and streaming progress remain a follow-up;
- Runtime installer/invocation metadata must migrate away from direct MCP;
- unconditional `--yolo` requires a trusted local/authenticated boundary.

## Verification

The implementation is accepted only when:

1. both gateway tools are registered by `create_mcp_server`;
2. capability recall invokes the Runtime registry and returns bounded metadata;
3. Agent invocation always contains `--yolo`, `--source tool`, and reports
   `mode=fast:fast` without using it as a model ID;
4. invalid workdirs and missing commands fail closed;
5. existing MCP bridge tests remain green;
6. external registration documentation points to `simplicio-agent mcp serve`;
7. a real stdio MCP client can list and call the new tools.
