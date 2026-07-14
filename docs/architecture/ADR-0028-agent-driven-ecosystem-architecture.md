# ADR-0028: Agent-driven ecosystem — Mapper observes, Dev CLI compiles, Loop converges, Runtime acts

- Status: accepted
- Date: 2026-07-13
- Related: simplicio-runtime#3134 (epic), simplicio-runtime#3135-#3140,
  simplicio-mapper#208-#209, simplicio-dev-cli#166-#167, simplicio-loop#261-#262,
  ADR-0001 (checkpoint mirror), ADR-0003 (runtime managed dependency)

## Context

The ecosystem consists of five separate repositories: `simplicio-agent`,
`simplicio-mapper`, `simplicio-dev-cli`, `simplicio-loop`, and
`simplicio-runtime`. simplicio-runtime#3134 supersedes an earlier proposal
that treated `simplicio-runtime` as a global authority over state and
scheduling across all five. That proposal is rejected: it would move
transcript, memory, goals, and provider/tool selection out of the agent and
into a coprocessor repo that has none of the context needed to own them, and
it would require a monorepo-style fusion this ecosystem has already rejected
once (ADR-0003).

## Decision

The ecosystem is a causal system **driven by simplicio-agent**, without
merging repositories. Each project's authority is scoped as follows:

| Project | Role in integrated mode | Does not own |
|---|---|---|
| `simplicio-agent` | product, session, TurnEngine, providers, ToolPipeline, memory, next-action choice, presentation | internal implementation of the other projects |
| `simplicio-mapper` | observes code/context and produces a verifiable `ContextSnapshot`/`ContextGraph` | plan, execution, or decision |
| `simplicio-dev-cli` | compiles goal+context into `PlanDAG`/`EffectProposal`/`VerificationPlan` | applying effects in integrated mode |
| `simplicio-loop` | computes convergence policy for a subworkflow: continue/replan/pause/stop | global scheduler, conversational session, or direct execution |
| `simplicio-runtime` | deterministic coprocessor: gate, mechanical edit, validation, and receipts/ledger for its own effects | transcript, memory, goals, provider, tool choice, or turn control |

### Canonical flow — on demand, not a mandatory chain

```
User/Surface
  -> AgentSession + TurnEngine
      |- Mapper: ContextSnapshot (when needed)
      |- Dev CLI: PlanDAG/VerificationPlan (when needed)
      |- Loop: ControlDecision for the subworkflow (when needed)
      `- ToolInvocationPipeline
           -> SimplicioBridge
               -> Runtime: Gate / Mechanical Edit / Validate / Receipt
  -> AgentEvent / response / continuation
```

Not every turn crosses all five projects. The agent picks the smallest
causal cone sufficient for the task — a simple turn must not call
Mapper/Dev CLI/Loop/Runtime when it doesn't need to.

### Real authorities

**Agent** owns: transcript/SessionDB and conversational memory;
prompt/toolset frozen per session incarnation; provider and tool selection;
TurnEngine, cognitive retries, approval UX, and cancellation; the real
checkpoint in the agent's shadow-git (ADR-0001, unchanged by this decision);
self-model/goals/context; integration of surfaces.

**Runtime** owns: deterministic validation of an `EffectRequest`; gate/policy
for the capabilities it implements; mechanical execution explicitly
authorized by the agent; receipt, ledger, and validation of those effects;
capability handshake and compatibility; its own reconstructible
caches/projections. The runtime's checkpoint remains evidence/mirror when
used — it does not replace the agent's shadow-git (ADR-0001).

### Federated contracts

There is no "sovereign" semantic registry in the runtime. Each producer owns
its schema: Agent (`GoalEnvelope`, `AgentEvent`, causal/session IDs); Mapper
(`ContextSnapshot`/`ContextGraph`); Dev CLI (`PlanDAG`/`EffectProposal`/
`VerificationPlan`); Loop (`ControlDecision`/`ConvergenceState`); Runtime
(`EffectRequest`/`GateDecision`/`EffectReceipt`/`ValidationReceipt`). A shared
package/manifest aggregates versions, fixtures, and compatibility without
transferring ownership — tracked in simplicio-runtime#3135.

## Consequences

- `simplicio-runtime` is confirmed, not revised, as a deterministic
  coprocessor (consistent with ADR-0003): it stays a managed, pinned
  dependency of the agent, never a control plane the agent answers to.
- No component other than the agent selects provider, tool, or next turn.
  Mapper never mutates or decides; an integrated Dev CLI never applies an
  effect; an integrated Loop never becomes a global scheduler; Runtime never
  picks the agent's next tool/action.
- A mutating effect always passes through the agent's ToolPipeline, gate,
  and checkpoint — there is no path that lets Runtime (or any other project)
  apply an effect the agent didn't authorize.
- Follow-up work (contracts, IDs, integration wiring, rollout) is tracked in
  the child issues listed above and is out of scope for this ADR, which
  records the architectural decision only.

## Alternatives considered

- **`simplicio-runtime` as global state/scheduler authority** (the original
  proposal superseded by simplicio-runtime#3134). Rejected: it would strip
  the agent of transcript, memory, goals, and provider/tool control — the
  exact authorities that make it the product — and hand them to a repo whose
  charter (per ADR-0003) is a deterministic, swappable actuator with its own
  independent release cadence and consumers (Homebrew, npm, Docker, desktop
  bundle).
- **Monorepo fusion of the five projects.** Rejected for the same reasons as
  ADR-0003: each project has independent consumers and lifecycle; fusion
  forks the ecosystem instead of unifying it.
- **A mandatory five-hop pipeline on every turn.** Rejected: most turns need
  only a subset of these components; forcing all five adds latency and
  tokens with no benefit, and violates the information-bottleneck goal of
  transmitting the smallest context that preserves fidelity.
