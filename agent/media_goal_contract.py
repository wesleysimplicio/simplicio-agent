"""Verifiable media pipeline goal contract."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

MEDIA_GOAL_SCHEMA = "simplicio.media-goal/v1"

@dataclass(frozen=True, slots=True)
class MediaGoalContract:
    goal: str
    input_refs: tuple[str, ...]
    output_format: str
    duration_s: float
    fps: int
    verifier: str
    timeline_ref: str = ""

    def __post_init__(self) -> None:
        for name in ("goal", "output_format", "verifier"):
            value = str(getattr(self, name)).strip()
            if not value: raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        refs = tuple(sorted({str(item).strip() for item in self.input_refs}))
        if not refs or any(not item for item in refs): raise ValueError("input_refs must be non-empty")
        object.__setattr__(self, "input_refs", refs)
        if float(self.duration_s) <= 0 or int(self.fps) <= 0: raise ValueError("duration_s and fps must be positive")
        object.__setattr__(self, "timeline_ref", str(self.timeline_ref).strip())

    def to_dict(self):
        return {"schema": MEDIA_GOAL_SCHEMA, "goal": self.goal, "input_refs": list(self.input_refs),
                "output_format": self.output_format, "duration_s": self.duration_s, "fps": self.fps,
                "verifier": self.verifier, "timeline_ref": self.timeline_ref}

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
