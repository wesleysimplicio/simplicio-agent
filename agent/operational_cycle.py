"""Bounded perception-to-reconciliation cycle for operational awareness.

The cycle composes existing event-store, operational-now, and prediction
contracts. It observes receipts, refuses actions whose fresh preconditions are
not present, and persists prediction reconciliation as another awareness
receipt. It never grants authority or executes an action itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable

from agent.belief_state import Freshness
from agent.event_store import (
    AwarenessReceipt,
    OperationalValueStatus,
)
from agent.operational_now import (
    Degradation,
    OperationalNowSnapshot,
    OperationalNowStore,
)
from agent.prediction_receipts import (
    Observation,
    ObservationState,
    PreconditionKind,
    PredictionOutcome,
    PredictionReceipt,
    prediction_evidence_digest,
)


@dataclass(frozen=True, slots=True)
class ActionDecision:
    """Fail-closed authorization input for the caller's existing action gate."""

    allowed: bool
    reason: str
    snapshot_hash: str
    missing_preconditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Prediction assessment plus the resulting materialized awareness state."""

    prediction: PredictionReceipt
    awareness_receipt: AwarenessReceipt
    snapshot: OperationalNowSnapshot


class OperationalAwarenessCycle:
    """Compose observation, precondition checking, and effect reconciliation."""

    def __init__(
        self,
        store: OperationalNowStore,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.store = store
        self._clock_ns = clock_ns

    def observe(self, receipts: Iterable[AwarenessReceipt]) -> OperationalNowSnapshot:
        """Append observations and rebuild the deterministic operational snapshot."""

        for receipt in receipts:
            self.store.append(receipt)
        return self.store.project()

    def snapshot(self) -> OperationalNowSnapshot:
        """Load a valid snapshot or replay the event log when it is absent/corrupt."""

        return self.store.load_or_rebuild()

    def authorize(self, prediction: PredictionReceipt) -> ActionDecision:
        """Check fresh, observed preconditions without executing the action."""

        snapshot = self.snapshot()
        if snapshot.degradation in {
            Degradation.BLOCKED,
            Degradation.CONFLICT,
            Degradation.STALE,
        }:
            return ActionDecision(
                False,
                f"awareness snapshot is {snapshot.degradation.value}",
                snapshot.snapshot_hash,
            )

        missing: list[str] = []
        for precondition in prediction.preconditions:
            if precondition.kind is PreconditionKind.BELIEF:
                resolved = snapshot.resolve(precondition.reference)
                if resolved is None:
                    missing.append(precondition.reference)
                    continue
                if getattr(resolved, "freshness", None) is not Freshness.FRESH:
                    missing.append(precondition.reference)
                continue

            if not self._has_receipt_evidence(snapshot, precondition.reference):
                missing.append(precondition.reference)

        if missing:
            return ActionDecision(
                False,
                "fresh prediction preconditions are missing",
                snapshot.snapshot_hash,
                tuple(sorted(set(missing))),
            )
        return ActionDecision(True, "fresh prediction preconditions verified", snapshot.snapshot_hash)

    def reconcile(
        self,
        prediction: PredictionReceipt,
        observations: Iterable[Observation],
        *,
        ambiguous_timeout: bool = False,
    ) -> ReconciliationResult:
        """Assess effects and persist the result as a provenance-bearing receipt."""

        assessed = prediction.assess(observations, ambiguous_timeout=ambiguous_timeout)
        evidence_digest = prediction_evidence_digest(assessed)
        error_state = assessed.prediction_error.state
        receipt = AwarenessReceipt(
            receipt_id=f"prediction-{evidence_digest}",
            path=f"prediction.{assessed.action_digest}",
            value={
                "outcome": assessed.outcome.value,
                "prediction_error": assessed.prediction_error.to_dict(),
                "update_decision": assessed.update_decision,
                "next_strategy_fingerprint": assessed.next_strategy_fingerprint,
            },
            status=(
                OperationalValueStatus.MEASURED
                if assessed.outcome is PredictionOutcome.MATCH
                else OperationalValueStatus.INFERRED
            ),
            freshness=(
                Freshness.FRESH
                if error_state is ObservationState.KNOWN
                else Freshness.UNKNOWN
            ),
            source="reconciler",
            source_event_id=evidence_digest,
            recorded_at_ns=self._clock_ns(),
            confidence=assessed.confidence,
            uncertainty=1.0 - assessed.confidence,
            evidence_handles=(evidence_digest,),
            payload={
                "prediction_receipt_digest": evidence_digest,
                "action_digest": assessed.action_digest,
            },
        )
        self.store.append(receipt)
        snapshot = self.store.project()
        return ReconciliationResult(assessed, receipt, snapshot)

    @staticmethod
    def _has_receipt_evidence(snapshot: OperationalNowSnapshot, reference: str) -> bool:
        for field in snapshot.fields.values():
            if reference in {
                field.source_event_id,
                field.handle,
                *field.evidence_handles,
            } and field.freshness is Freshness.FRESH:
                return True
        for belief in snapshot.beliefs.values():
            if reference in {
                belief.source_event_id,
                *belief.evidence_handles,
            } and belief.freshness is Freshness.FRESH:
                return True
        return False


__all__ = ["ActionDecision", "OperationalAwarenessCycle", "ReconciliationResult"]
