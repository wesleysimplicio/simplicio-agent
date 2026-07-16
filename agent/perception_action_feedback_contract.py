"""Bounded perception-action-feedback contract for issue #182.

Proves the narrow vertical slice the issue asks for: in a mutable
browser/desktop environment, an action must never fire against a stale
perception. Every planned action carries the state hash it was planned
against; before firing, the actuator must supply the environment's current
state hash. If they differ, the contract forces a re-observe instead of
acting on old coordinates/elements -- it never silently proceeds.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

PAF_SCHEMA = "simplicio.perception-action-feedback/v1"


@dataclass(frozen=True, slots=True)
class PlannedAction:
    action: str
    target_ref: str
    planned_state_hash: str

    def __post_init__(self) -> None:
        for name in ("action", "target_ref", "planned_state_hash"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class FeedbackVerdict:
    action: str
    target_ref: str
    verdict: str  # "fire" | "reobserve"
    reason: str

    def to_dict(self) -> dict:
        return {
            "schema": PAF_SCHEMA,
            "action": self.action,
            "target_ref": self.target_ref,
            "verdict": self.verdict,
            "reason": self.reason,
        }

    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def should_fire(self) -> bool:
        return self.verdict == "fire"


def hash_state(observed_snapshot: str) -> str:
    """Content-hash of a DOM/window snapshot string, so callers never compare raw payloads."""
    return hashlib.sha256(str(observed_snapshot).encode("utf-8")).hexdigest()


def gate_action(planned: PlannedAction, current_state_hash: str) -> FeedbackVerdict:
    current = str(current_state_hash).strip()
    if not current:
        raise ValueError("current_state_hash must be non-empty")
    if current != planned.planned_state_hash:
        return FeedbackVerdict(
            planned.action, planned.target_ref, "reobserve",
            reason="environment state changed since planning; stale coordinates/elements must not be acted on",
        )
    return FeedbackVerdict(
        planned.action, planned.target_ref, "fire",
        reason="current state matches the state the action was planned against",
    )
