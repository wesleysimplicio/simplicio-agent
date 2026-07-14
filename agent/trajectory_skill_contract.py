"""Bounded, review-gated trajectory-to-skill contract."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

TRAJECTORY_SKILL_SCHEMA = "simplicio.trajectory-skill/v1"

@dataclass(frozen=True, slots=True)
class TrajectorySkillCandidate:
    trajectory_hash: str
    status: str
    steps: tuple[str, ...]
    provenance: str
    test_fixture: str
    confidence: float
    review_required: bool = True

    def __post_init__(self) -> None:
        for name in ("trajectory_hash", "status", "provenance", "test_fixture"):
            value = str(getattr(self, name)).strip()
            if not value: raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "steps", tuple(str(item).strip() for item in self.steps))
        if not self.steps or any(not item for item in self.steps):
            raise ValueError("steps must be non-empty")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not isinstance(self.review_required, bool):
            raise TypeError("review_required must be boolean")

    @property
    def eligible(self) -> bool:
        return self.status == "completed_verified" and bool(self.test_fixture)

    def to_dict(self):
        return {"schema": TRAJECTORY_SKILL_SCHEMA, "trajectory_hash": self.trajectory_hash,
                "status": self.status, "steps": list(self.steps), "provenance": self.provenance,
                "test_fixture": self.test_fixture, "confidence": self.confidence,
                "review_required": self.review_required, "eligible": self.eligible}

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
