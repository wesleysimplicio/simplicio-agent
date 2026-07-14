# Simplicio Operational Manual

Canonical runtime operational reference for Simplicio Agent. This document is
the source of truth for **how the agent executes**, the **boundaries it must
never cross**, and the **interaction contract between the Hermes/SIMPLICIO
reasoning layer and the Simplicio Runtime execution kernel**.

It is referenced by `skills/operations/simplicio-release-operations` and by the
digital-consciousness gap analysis as the document that defines — and rejects —
specific autonomy anti-patterns.

## 1. Execution model (runtime-first)

Per ADR-0010 the mandatory hierarchy is:

1. **Hermes reasons and coordinates** — selects actions, interprets results,
   converses, plans. It is not the preferred execution layer.
2. **Simplicio CLI executes every action it can** — read/search/Git/diff/tests/
   build/shell/mutation/validation/evidence/checkpoints/delivery all attempt
   `simplicio <command>` first.
3. **Simplicio MCP is fallback transport only** when CLI is unavailable or a
   warm MCP path is configured.
4. **Native Hermes execution is a temporary capability exception** — used only
   when the Runtime cannot perform an action, and must be reported as
   `UNVERIFIED | runtime capability gap`, then closed with Runtime parity.

The permanent loop: reason in Hermes → execute in Runtime → detect a gap →
use native execution only if required → close or contract Runtime parity →
use the Runtime on the next equivalent interaction.

## 2. LLM routing policy

- The **Agent (bot)** always uses a remote provider (`openai-codex` /
  `gpt-5.6-terra`) for reasoning.
- Only the **Runtime** may use a local LLM (`llama.cpp` / `llama-server`) when
  `offline_first = true` and `remote_allowed = false`.
- Model resolution is driven by `runtime.toml` `default_model`, which must
  point at a real GGUF present under `~/.simplicio/models/`. A model id that
  does not resolve to a file fails the `gguf-model` doctor check and breaks
  every Runtime tool that needs local inference.

## 3. Observability and gating (hard rules)

The Simplicio execution surface is **observable and gated**. The following are
explicit anti-patterns this manual rejects and that must never be introduced:

- **Hidden autonomy** — executing actions the user cannot see or audit.
- **Unbounded always-on autonomy** — loops that run without evidence-gated
  halting or a human checkpoint.
- **Hidden self-modification** — the runtime/kernel mutating its own code or
  configuration without a receipt and human approval.

All mutating operations must go through:

- **Action gate** — every consequential action is gated, logged, and reversible
  where possible (checkpoints / undo ledger).
- **Evidence ledger (HBP)** — each claimed result carries a receipt
  (artifact hash, command output, or benchmark number). No claim without a
  receipt.
- **Evidence-gated halting** — loops stop only when confidence is high *and*
  the turn produced real verification (Asolaria act-halting).

## 4. Runtime adapters (smoke surface)

The standard-IO smoke exercises this chain:

```
runtime task/run -> mapper -> dev-cli -> edit -> validate -> loop/evidence
```

| Adapter | Purpose | Pass condition |
|---------|---------|----------------|
| `simplicio-mapper` | context mapping of a request | binary resolves + runs |
| `simplicio-dev-cli` | focused dev/test execution | binary resolves + runs |
| `simplicio-prompt` | prompt/subagent dispatch | binary resolves + runs |
| `simplicio-loop` | orient/review/learn loop | binary resolves + runs |
| `llama-server` | local LLM serving | binary resolves + serves |
| `simplicio-runtime` | kernel self-check | version + receipt crypto + benchmark pass |

Required artifacts (must exist at repo root for smoke to pass):

- `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` — this file.
- `examples/EXAMPLES.md` — worked end-to-end examples of the request→delivery
  chain.

## 5. Update and rollback

- Distribution is an **immutable, versioned bundle** under
  `~/.simplicio_agent/releases/<digest>/`, with `current` symlinked to the
  active bundle.
- The bot loads code from `releases/<digest>/code/agent`, not from `build/lib`.
- Restart of the live bot is performed by the operator via `/restart` in
  Discord; the gateway LaunchAgent is intentionally not self-restartable from
  inside the session (KeepAlive respawns it).
- Rollback = repoint `current` to the previous digest and restart.

## 6. Prohibited operations (summary)

- Do not rename `HERMES_*` env vars or internal identifiers — they are a
  cross-repo contract; `SIMPLICIO_AGENT_*` are accepted aliases only.
- Do not introduce hidden autonomy, unbounded loops, or silent self-modifying
  code.
- Do not ship a model id in `runtime.toml` that has no corresponding GGUF file.
- Do not let the Agent reason *and* execute locally at the same time — remote
  reasoning, local execution only.
