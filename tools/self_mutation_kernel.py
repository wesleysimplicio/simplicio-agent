"""Bounded composition boundary for transactional self-modification.

The lower-level snapshot, shadow-effect, equivalence, canary, and promotion
modules deliberately remain independently testable.  This module composes
them into one fail-closed operation: a candidate is shadowed in a disposable
copy, promoted only after an equivalent report and an exact canary pin, and
automatically rolled back when the live health check fails.

``shadow_runner`` is the existing invocation choke-point's seam.  It receives
the disposable candidate tree and an :class:`EffectInterceptor`; callers must
route effects through that interceptor and return an equivalence-gate report.
No process is started or stopped here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from tools.equivalence_gate import (
    CanaryController,
    FeatureFlagStore,
    evaluate_shadow_reports,
)
from tools.promotion_controller import (
    PromotionController,
    PromotionResult,
    build_promotion_receipt,
)
from tools.shadow_effects import (
    EffectInterceptor,
    FilesystemSentinel,
    NetworkSentinel,
    ShadowOverlay,
    ShadowReceipt,
    compare_effect_sequences,
)
from tools.transaction_primitives import (
    TransactionJournal,
    snapshot_tree,
)


SELF_MUTATION_SCHEMA = "simplicio.self-mutation-receipt/v1"


class SelfMutationError(RuntimeError):
    """A self-modification boundary cannot safely continue."""


@dataclass(frozen=True)
class SelfMutationReceipt:
    """Stable HBP evidence for one attempted self-modification."""

    status: str
    snapshot_before: str | None = None
    snapshot_after: str | None = None
    rollback_to: str | None = None
    shadow_receipt_digest: str | None = None
    equivalence_verdict: str = "reject"
    canary_enabled: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        for field_name in ("status", "equivalence_verdict", "reason"):
            value = str(getattr(self, field_name))
            if "\n" in value:
                raise ValueError(f"{field_name} must be a single line")
            object.__setattr__(self, field_name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SELF_MUTATION_SCHEMA,
            "hbp_schema": "simplicio.hbp-receipt/v1",
            "status": self.status,
            "snapshot_before": self.snapshot_before,
            "snapshot_after": self.snapshot_after,
            "rollback_to": self.rollback_to,
            "shadow_receipt_digest": self.shadow_receipt_digest,
            "equivalence_verdict": self.equivalence_verdict,
            "canary_enabled": self.canary_enabled,
            "reason": self.reason,
        }

    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


ShadowRunner = Callable[[Path, EffectInterceptor], Mapping[str, Any]]


class SelfMutationKernel:
    """Run one bounded shadow/equivalence/canary/promotion transaction."""

    def __init__(self, root: str | Path, *, slice_name: str = "self-mutation"):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.promotion = PromotionController(self.root / "promotion")
        flags = FeatureFlagStore(self.root / "flags")
        self.canary = CanaryController(
            flags, self.root / "canary-journal.jsonl", slice_name
        )
        self.journal = TransactionJournal(self.root / "mutation-journal.jsonl")

    def _finish(self, receipt: SelfMutationReceipt) -> SelfMutationReceipt:
        self.journal.append_mutation(
            intent="self-mutation",
            actor="simplicio-agent",
            snapshot_before=receipt.snapshot_before,
            snapshot_after=receipt.snapshot_after,
            fencing_token="self-mutation",
            result=receipt.to_dict(),
        )
        return receipt

    def _rejected(
        self,
        before: str | None,
        reason: str,
        *,
        shadow_digest: str | None = None,
        verdict: str = "reject",
    ) -> SelfMutationReceipt:
        return self._finish(
            SelfMutationReceipt(
                status="rejected",
                snapshot_before=before,
                shadow_receipt_digest=shadow_digest,
                equivalence_verdict=verdict,
                reason=reason,
            )
        )

    def apply(
        self,
        baseline: str | Path,
        candidate: str | Path,
        *,
        shadow_runner: ShadowRunner,
        profile_id: str,
        session_id: str,
        promoted_commit: str,
        fencing_token: int,
        health_check: Callable[..., object],
        tolerances: Mapping[str, Any] | None = None,
        timeout_s: float = 60.0,
    ) -> SelfMutationReceipt:
        """Attempt one candidate promotion and return a durable receipt.

        The runner's mapping must contain ``equivalence_report`` in the
        ``simplicio.shadow-report/v1`` shape.  It may also contain
        ``legacy_effects`` and ``shadow_effects`` sequences; when omitted both
        are empty and therefore equivalent.  All effects are expected to go
        through the supplied interceptor.
        """

        baseline_path = Path(baseline).expanduser().resolve()
        candidate_path = Path(candidate).expanduser().resolve()
        before: str | None = None
        canary_active = False
        try:
            before = snapshot_tree(baseline_path).snapshot_id
            current = self.promotion.current()
            if current is None:
                self.promotion.seed(baseline_path)
                current = self.promotion.current()
            if current != before:
                return self._rejected(before, "baseline is not the current snapshot")

            candidate_digest = snapshot_tree(candidate_path).snapshot_id
            sentinel = FilesystemSentinel.capture(baseline_path)
            network = NetworkSentinel()
            with tempfile.TemporaryDirectory(prefix="simplicio-shadow-") as temporary:
                shadow_tree = Path(temporary) / "candidate"
                shutil.copytree(candidate_path, shadow_tree, symlinks=False)
                overlay = ShadowOverlay(Path(temporary) / "overlay")
                interceptor = EffectInterceptor(
                    overlay=overlay, network_sentinel=network
                )
                result = shadow_runner(shadow_tree, interceptor)
                if not isinstance(result, Mapping):
                    raise SelfMutationError("shadow runner must return an object")
                if any(decision.executed for decision in interceptor.decisions):
                    raise SelfMutationError(
                        "shadow runner executed an intercepted effect"
                    )
                effect_report = compare_effect_sequences(
                    result.get("legacy_effects", ()),
                    result.get("shadow_effects", ()),
                )
                filesystem = sentinel.check()
                shadow_receipt = ShadowReceipt(
                    before,
                    effect_report,
                    filesystem.to_dict(),
                    network.to_dict(),
                )

            if snapshot_tree(candidate_path).snapshot_id != candidate_digest:
                return self._rejected(
                    before,
                    "candidate changed during shadow run",
                    shadow_digest=shadow_receipt.digest,
                )
            if not filesystem.passed:
                return self._rejected(
                    before,
                    "baseline changed during shadow run",
                    shadow_digest=shadow_receipt.digest,
                )
            raw_report = result.get("equivalence_report")
            if not isinstance(raw_report, Mapping):
                raise SelfMutationError("equivalence_report is required")
            gate = evaluate_shadow_reports([raw_report], tolerances=tolerances)
            if gate["verdict"] != "promote":
                return self._rejected(
                    before,
                    "equivalence gate did not promote",
                    shadow_digest=shadow_receipt.digest,
                    verdict=str(gate["verdict"]),
                )
            if not self.canary.activate(profile_id, session_id):
                return self._rejected(
                    before,
                    "canary activation receipt failed",
                    shadow_digest=shadow_receipt.digest,
                    verdict="promote",
                )
            canary_active = True
            receipt = build_promotion_receipt(
                snapshot_before=before,
                candidate_digest=candidate_digest,
                promoted_commit=promoted_commit,
                fencing_token=fencing_token,
            )
            promoted: PromotionResult = self.promotion.promote(
                candidate_path,
                receipt,
                health_check,
                timeout_s=timeout_s,
            )
            if promoted.rolled_back:
                self.canary.rollback_on_divergence(
                    profile_id,
                    session_id,
                    divergence_rate=1.0,
                    threshold=0.0,
                )
                canary_active = False
                return self._finish(
                    SelfMutationReceipt(
                        status="rolled_back",
                        snapshot_before=before,
                        snapshot_after=promoted.after_digest,
                        rollback_to=promoted.before_digest,
                        shadow_receipt_digest=shadow_receipt.digest,
                        equivalence_verdict="promote",
                        reason=promoted.health.reason or "health check failed",
                    )
                )
            return self._finish(
                SelfMutationReceipt(
                    status="committed",
                    snapshot_before=before,
                    snapshot_after=promoted.after_digest,
                    shadow_receipt_digest=shadow_receipt.digest,
                    equivalence_verdict="promote",
                    canary_enabled=canary_active,
                    reason="equivalence gate and health check passed",
                )
            )
        except Exception as exc:
            if canary_active:
                self.canary.rollback_on_divergence(
                    profile_id,
                    session_id,
                    divergence_rate=1.0,
                    threshold=0.0,
                )
            return self._rejected(
                before, f"self-mutation blocked: {type(exc).__name__}: {exc}"
            )


__all__ = [
    "SELF_MUTATION_SCHEMA",
    "SelfMutationError",
    "SelfMutationReceipt",
    "SelfMutationKernel",
]
