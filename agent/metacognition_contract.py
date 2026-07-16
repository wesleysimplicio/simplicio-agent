"""Bounded metacognition contract for issue #173.

Composes existing verified receipts (self-model capability limits, belief
freshness/confidence, prediction-error calibration) into one deterministic
verdict about whether a claim the agent is about to make is metacognitively
grounded, instead of trusting the model's own confident-sounding prose. This
does not implement general introspection; it only checks the three
mechanical signals the issue names as prerequisites (Belief State, Self-model
and Prediction Receipts).
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

METACOGNITION_SCHEMA = "simplicio.metacognition/v1"


@dataclass(frozen=True, slots=True)
class MetacognitiveSignal:
    claim: str
    within_known_capability: bool
    belief_confidence: float
    calibration_error: float  # |predicted - observed| from prediction receipts, 0..1

    def __post_init__(self) -> None:
        claim = str(self.claim).strip()
        if not claim:
            raise ValueError("claim must be non-empty")
        object.__setattr__(self, "claim", claim)
        for name in ("belief_confidence", "calibration_error"):
            value = float(getattr(self, name))
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MetacognitiveVerdict:
    claim: str
    grounded: bool
    reason: str
    belief_confidence: float
    calibration_error: float

    def to_dict(self) -> dict:
        return {
            "schema": METACOGNITION_SCHEMA,
            "claim": self.claim,
            "grounded": self.grounded,
            "reason": self.reason,
            "belief_confidence": self.belief_confidence,
            "calibration_error": self.calibration_error,
        }

    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


# A claim needs at least this much belief confidence and at most this much
# historical calibration error to be reported as grounded rather than hedged.
MIN_GROUNDED_CONFIDENCE = 0.6
MAX_GROUNDED_CALIBRATION_ERROR = 0.3


def evaluate_claim(signal: MetacognitiveSignal) -> MetacognitiveVerdict:
    if not signal.within_known_capability:
        return MetacognitiveVerdict(
            signal.claim, False, "claim falls outside a known/verified capability boundary",
            signal.belief_confidence, signal.calibration_error,
        )
    if signal.belief_confidence < MIN_GROUNDED_CONFIDENCE:
        return MetacognitiveVerdict(
            signal.claim, False,
            f"belief_confidence {signal.belief_confidence:.2f} below grounded threshold {MIN_GROUNDED_CONFIDENCE}",
            signal.belief_confidence, signal.calibration_error,
        )
    if signal.calibration_error > MAX_GROUNDED_CALIBRATION_ERROR:
        return MetacognitiveVerdict(
            signal.claim, False,
            f"calibration_error {signal.calibration_error:.2f} above grounded threshold {MAX_GROUNDED_CALIBRATION_ERROR}",
            signal.belief_confidence, signal.calibration_error,
        )
    return MetacognitiveVerdict(
        signal.claim, True, "within known capability, confident, and historically well-calibrated",
        signal.belief_confidence, signal.calibration_error,
    )
