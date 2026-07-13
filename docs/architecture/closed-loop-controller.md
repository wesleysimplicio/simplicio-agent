# Closed-loop controller contract

`agent.closed_loop_controller` is the first bounded policy slice for issue
#161. It is pure: it receives a goal, an explicit `StateEstimate`, candidate
actions, and a versioned `ControllerPolicy`; it returns a serializable
`ControllerDecision`. It never invokes tools or grants authority. The Runtime
action gate remains the enforcement boundary.

The policy fails closed at each observation boundary:

- unknown/stale state, conflicts, missing confidence, or a committed effect
  return `observe`;
- unavailable capability returns `wait`;
- action cost ceilings return `block`;
- publication, deletion, payment, credentials, privilege escalation,
  external communication, irreversible actions, and explicit gate requests
  return `clarify`;
- only fresh, sufficiently confident, available, budget-fitting candidates
  can return `action`.

Candidate order cannot affect the result. Eligible candidates are ordered by
the policy's versioned cost score and then by `action_digest`. Decisions carry
the predicted effect, cost, verifier, selected digest, alternatives, and a
stable reason code; they do not expose chain-of-thought.

This contract deliberately does not own goal mutation, state persistence,
resource governance, observation, reconciliation, or execution. Those remain
with the existing GoalContract, awareness/receipt work, resource governor, and
Runtime action gate.
