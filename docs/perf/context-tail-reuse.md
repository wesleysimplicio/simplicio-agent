# Bounded context tail reuse

`agent.token_economy.PaidArtifactRegistry.render()` is the bounded Issue #22
slice for repeated context references.

- Registration records a positive measured rough-token cost and does not call
  the materializer.
- Admission is capped by `max_resident` before materialization.
- The first admitted emission contains the body; later emissions for the same
  content address contain only `⟦context:<digest>⟧`.
- `ContextReferenceResult.cache_hits`, `tokens_saved`, and
  `context_handles` expose local evidence. Receipts remain content-addressed
  and retain the original positive cost; cache hits are not reported as fake
  zero-token work.
- `preprocess_context_references(..., artifact_registry=registry)` opts the
  existing `@file`, `@folder`, `@git`, `@diff`, `@staged`, and `@url` expansion
  path into this behavior.

This is not the full Issue #22 DoD. It does not prove provider-side token
billing, persistence across process restarts, prompt-cache hit rates, or
mapper/runtime integration. The stable prompt-cache prefix is untouched
because the registry only changes attached-context blocks after reference
expansion.
