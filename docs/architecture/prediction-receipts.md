# Prediction receipt contract

`agent.prediction_receipts.PredictionReceipt` is the bounded contract for
learning from an action's observed effects. Build it before the mutating
action with `belief:<ref>` and/or `receipt:<sha>` preconditions, concrete
`Observation.known(...)` expected effects, a verifier, rollback plan, and
model-only `Counterfactual` entries for `no_action` and an alternative.

After the existing action gate, call `assess(...)`. It returns a new immutable
receipt. `match` is safe evidence, `partial_match`/`mismatch` request a belief
and strategy update, `unknown` requests reconciliation, and `error` escalates.
Unknown and error are never silently converted into mismatches or retries.

`to_json()` is compact canonical JSON (sorted keys, stable separators) for
replay and hashing. `record_ledger()` connects that payload to the existing
content-addressed receipts ledger. Counterfactuals are declarative and reject
any execution mode other than `model_only`.
