# Native 1.4 promotion controller contract

`tools/promotion_controller.py` is the bounded #341 boundary for promoting a
verified slot. It does not own process startup, restart, drain, or long-term
observation; those remain supervisor responsibilities. The controller does
own the safety-critical order of operations:

1. Validate a `simplicio.promotion/v1` receipt. The receipt must name the
   currently active snapshot, the candidate content digest, a commit, and an
   active fenced lease.
2. Copy the candidate into `slots/<digest>/`, calculate the complete snapshot
   digest, and reject a receipt whose digest does not match the staged slot.
3. Swap `current` atomically with `os.replace`. A symlink is used where the
   platform permits it; the fallback is an atomically replaced file containing
   the same relative `slots/<digest>` target.
4. Run the live health callback within the configured timeout. The callback
   must attest `healthy`, the promoted commit, and the promoted digest. An
   explicit `smoke: false` also fails the gate.
5. On health failure, timeout, or commit/digest mismatch, restore the prior
   pointer and append a `rollback_intent` journal record. The returned intent
   asks the supervisor to restore the prior snapshot and restart the process;
   this module never restarts its own process.

The journal is local, append-only, and hash chained through the existing
`TransactionJournal`. A successful result is committed only after live
attestation; a failed result has `promoted: false`, `rolled_back: true`, and a
machine-readable `automatic_rollback` intent. This slice proves deterministic
local slot/pointer/health behavior only: supervisor integration, in-flight
drain, kill-point matrices, rollback health, delayed observation, and clean
machine delivery remain `UNVERIFIED| outside bounded controller scope`.
