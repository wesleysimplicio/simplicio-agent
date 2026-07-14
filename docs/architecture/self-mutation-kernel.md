# Bounded self-mutation kernel (#315)

`tools/self_mutation_kernel.py` is the composition boundary for one
self-modification attempt.  It does not own process lifecycle or release
fetching; callers provide the invocation choke point (`shadow_runner`) and a
health callback.

The order is deliberately fail-closed:

1. Hash the baseline and seed or validate the current promotion slot.
2. Run the candidate in a disposable copy with `EffectInterceptor`; writes
   stay in `ShadowOverlay`, and network/provider/platform effects are blocked.
3. Require unchanged baseline evidence, equivalent effect sequences, a
   passing `ShadowReceipt`, and an `evaluate_shadow_reports` verdict of
   `promote`.
4. Pin the exact profile/session canary, then atomically promote through
   `PromotionController`.
5. If health fails, restore the previous pointer, disable the canary, and
   emit one hash-chained HBP receipt with before/after/rollback digests.

Every path emits `simplicio.self-mutation-receipt/v1` evidence.  A rejected
shadow or equivalence result leaves the previous slot and the baseline tree
usable.  Live process restart, release acquisition, and commit attestation
remain outside this bounded slice and are therefore `UNVERIFIED|` until a
supervisor supplies those callbacks and evidence.
