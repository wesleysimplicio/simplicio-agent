"""Bounded value-of-information gate for issue #175.

Before an uncertain or irreversible action, this contract decides whether a
cheap observation should be taken first (it discriminates between live
hypotheses) or whether the agent should act directly. This is a deliberately
narrow policy experiment -- not a claim of Expected Free Energy / active
inference as proven consciousness theory -- scoped exactly to the issue's own
framing ("Expected Free Energy será tratada como experimento de policy, não
teoria comprovada de consciência").
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

VOI_SCHEMA = "simplicio.value-of-information/v1"


@dataclass(frozen=True, slots=True)
class ObservationOption:
    name: str
    cost: float
    discriminates: tuple[str, ...]  # hypothesis ids this observation can rule out

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("name must be non-empty")
        object.__setattr__(self, "name", name)
        if float(self.cost) < 0:
            raise ValueError("cost must be >= 0")
        object.__setattr__(
            self, "discriminates", tuple(sorted({str(h).strip() for h in self.discriminates if str(h).strip()}))
        )


@dataclass(frozen=True, slots=True)
class ValueOfInformationDecision:
    live_hypotheses: tuple[str, ...]
    action_cost: float
    action_irreversible: bool
    observe_or_act: str
    chosen_observation: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "schema": VOI_SCHEMA,
            "live_hypotheses": list(self.live_hypotheses),
            "action_cost": self.action_cost,
            "action_irreversible": self.action_irreversible,
            "observe_or_act": self.observe_or_act,
            "chosen_observation": self.chosen_observation,
            "reason": self.reason,
        }

    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def decide_observe_or_act(
    *,
    live_hypotheses: tuple[str, ...],
    action_cost: float,
    action_irreversible: bool,
    observations: tuple[ObservationOption, ...],
) -> ValueOfInformationDecision:
    """Deterministically choose between observing first and acting directly.

    Policy: if fewer than 2 hypotheses are live, there is nothing left to
    discriminate -- act. Otherwise, among observations that discriminate at
    least one live hypothesis and cost less than the action, pick the
    cheapest; if none qualify, act directly (paying the irreversible cost
    knowingly rather than stalling on an observation that buys nothing).
    """
    hyps = tuple(sorted({str(h).strip() for h in live_hypotheses if str(h).strip()}))
    if float(action_cost) < 0:
        raise ValueError("action_cost must be >= 0")

    if len(hyps) < 2:
        return ValueOfInformationDecision(
            hyps, float(action_cost), bool(action_irreversible), "act", "",
            reason="fewer than 2 live hypotheses; nothing to discriminate",
        )

    candidates = [
        obs for obs in observations
        if obs.cost < action_cost and any(h in hyps for h in obs.discriminates)
    ]
    if not candidates:
        reason = (
            "no observation discriminates a live hypothesis below action cost"
            if not action_irreversible
            else "no cheap discriminating observation available; proceeding with irreversible action knowingly"
        )
        return ValueOfInformationDecision(
            hyps, float(action_cost), bool(action_irreversible), "act", "", reason=reason,
        )

    cheapest = min(candidates, key=lambda obs: (obs.cost, obs.name))
    return ValueOfInformationDecision(
        hyps, float(action_cost), bool(action_irreversible), "observe", cheapest.name,
        reason=f"'{cheapest.name}' discriminates a live hypothesis for less than the action cost",
    )
