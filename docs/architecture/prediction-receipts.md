# Prediction receipt contract

`agent.prediction_receipts.PredictionReceipt` is the bounded contract for
learning from an action's observed effects. Build it before the mutating
action with fresh `Precondition` entries, concrete `Observation.known(...)`
expected effects, a recomputable `Verifier`, a rollback plan, explicit
`TimeoutReconciliation`, hard `HardPolicyConstraint` limits, a
`strategy_fingerprint`, and model-only `Counterfactual` entries for
`no_action` and an alternative.

After the existing action gate, call `assess(...)`. It returns a new immutable
receipt. `match` is safe evidence, `partial_match`/`mismatch` request a belief
and strategy update, `unknown` requests reconciliation, and `error` escalates.
If the caller marks `ambiguous_timeout=True`, reconciliation is forced through
the declared effect journal and verifier query before any retry. Unknown and
error are never silently converted into mismatches or retries.

`to_json()` is compact canonical JSON (sorted keys, stable separators) for
replay and hashing. `record_ledger()` connects that payload to the existing
content-addressed receipts ledger. Counterfactuals are declarative and reject
any execution mode other than `model_only`. Non-match outcomes emit a
deterministic `failure_fingerprint` plus a changed
`next_strategy_fingerprint`, so repeated equivalent failures can be recognized
without claiming that calibration or end-to-end idempotence is already proven
in this layer.
