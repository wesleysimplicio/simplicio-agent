"""Real reference implementation for issue #315 — Kernel de auto-modificação
transacional e shadow equivalence.

The shipped tree already contains the bounded slices this epic tracks (snapshot/
journal/shadow-run, canary, equivalence gate, atomic promotion, automatic rollback)
wired into the agent runtime. This module is a *self-contained, dependency-free*
reference implementation of the **transactional self-modification kernel** contract
described in #315 so the capability has a directly runnable, testable artifact that
any integrator can study without importing the whole runtime.

Core guarantees (all exercised by tests):
* Snapshot before mutation; journal of the effect.
* Shadow-run: the candidate mutation is applied to a copy; an equivalence predicate
  is evaluated on the same probe inputs for the current vs shadow state.
* Atomic promotion: if equivalence holds AND the canary passes, the mutation is
  promoted; otherwise it is rolled back to the snapshot and a receipt is emitted.
* Every path produces an HBP receipt (hash, block, provenance).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


def _digest(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


@dataclass
class Receipt:
    action_digest: str
    kind: str
    status: str  # committed | rolled_back
    snapshot_digest: str
    shadow_digest: str
    equivalence: bool
    canary_ok: bool
    note: str = ""

    def to_hbp(self) -> Dict[str, Any]:
        return {
            "hbp": True,
            "action_digest": self.action_digest,
            "kind": self.kind,
            "status": self.status,
            "snapshot_digest": self.snapshot_digest,
            "shadow_digest": self.shadow_digest,
            "equivalence": self.equivalence,
            "canary_ok": self.canary_ok,
            "note": self.note,
        }


@dataclass
class SelfModKernel:
    """Minimal transactional self-modification kernel.

    ``apply(mutator, probe, equivalence, canary)``:
      * snapshot = current state (deep-ish copy via dict)
      * shadow = snapshot + mutator
      * equivalence = equivalence(probe, current) == equivalence(probe, shadow)
      * canary = canary(shadow)
      * on success: current <- shadow (promote), emit committed receipt
      * on failure: current unchanged (rollback), emit rolled_back receipt
    """

    state: Dict[str, Any] = field(default_factory=dict)
    receipts: List[Receipt] = field(default_factory=list)

    def _snapshot(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.state, default=str))

    def apply(
        self,
        mutator: Callable[[Dict[str, Any]], None],
        probe: Any,
        equivalence: Callable[[Any, Dict[str, Any]], Any],
        canary: Callable[[Dict[str, Any]], bool] = lambda s: True,
        kind: str = "self_mod",
    ) -> Receipt:
        snapshot = self._snapshot()
        shadow = self._snapshot()
        mutator(shadow)

        equiv_before = equivalence(probe, snapshot)
        equiv_after = equivalence(probe, shadow)
        is_equiv = equiv_before == equiv_after
        canary_ok = canary(shadow)

        action_digest = _digest(
            {"mutator": getattr(mutator, "__name__", repr(mutator)), "probe": probe, "shadow": shadow}
        )
        snap_digest = _digest(snapshot)
        shadow_digest = _digest(shadow)

        if is_equiv and canary_ok:
            self.state = shadow
            receipt = Receipt(
                action_digest=action_digest,
                kind=kind,
                status="committed",
                snapshot_digest=snap_digest,
                shadow_digest=shadow_digest,
                equivalence=is_equiv,
                canary_ok=canary_ok,
            )
        else:
            receipt = Receipt(
                action_digest=action_digest,
                kind=kind,
                status="rolled_back",
                snapshot_digest=snap_digest,
                shadow_digest=shadow_digest,
                equivalence=is_equiv,
                canary_ok=canary_ok,
                note="rollback: equivalence={} canary={}".format(is_equiv, canary_ok),
            )
        self.receipts.append(receipt)
        return receipt
