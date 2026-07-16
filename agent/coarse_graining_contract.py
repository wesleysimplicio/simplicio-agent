"""Bounded coarse-graining contract for issue #178.

Links micro/meso/macro/narrative summaries of a run through reversible
handles: every level above ``micro`` must be able to point back at the exact
micro-events it was built from (by content hash), so a narrative summary
never loses an AC, error, number, or causal link -- it can always be expanded
back to source. This module only enforces that linkage; it reuses the
rate-distortion context (#137) and J-Space (#140) contracts for the actual
compression policy.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

COARSE_GRAINING_SCHEMA = "simplicio.coarse-graining/v1"
LEVELS = ("micro", "meso", "macro", "narrative")


def _hash_event(event: str) -> str:
    return hashlib.sha256(event.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MicroEvent:
    handle: str
    content: str

    def __post_init__(self) -> None:
        handle = str(self.handle).strip()
        content = str(self.content)
        if not handle:
            raise ValueError("handle must be non-empty")
        if not content.strip():
            raise ValueError("content must be non-empty")
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class CoarseGrainLevel:
    level: str
    summary: str
    source_handles: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}")
        summary = str(self.summary).strip()
        if not summary:
            raise ValueError("summary must be non-empty")
        object.__setattr__(self, "summary", summary)
        handles = tuple(sorted({str(h).strip() for h in self.source_handles if str(h).strip()}))
        if self.level != "micro" and not handles:
            raise ValueError(f"level '{self.level}' must reference at least one source handle")
        object.__setattr__(self, "source_handles", handles)


@dataclass(frozen=True, slots=True)
class CoarseGrainedTrace:
    micro_events: tuple[MicroEvent, ...]
    levels: tuple[CoarseGrainLevel, ...]

    def to_dict(self) -> dict:
        return {
            "schema": COARSE_GRAINING_SCHEMA,
            "micro_events": [{"handle": e.handle, "content_hash": _hash_event(e.content)} for e in self.micro_events],
            "levels": [
                {"level": lvl.level, "summary": lvl.summary, "source_handles": list(lvl.source_handles)}
                for lvl in self.levels
            ],
        }

    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def expand(self, level_index: int) -> tuple[MicroEvent, ...]:
        """Return the micro-events a given level's summary can be traced back to."""
        level = self.levels[level_index]
        by_handle = {e.handle: e for e in self.micro_events}
        if level.level == "micro":
            handle = self.micro_events[level_index].handle if self.micro_events else None
            return (by_handle[handle],) if handle in by_handle else ()
        missing = [h for h in level.source_handles if h not in by_handle]
        if missing:
            raise ValueError(f"level '{level.level}' references unknown micro handles: {missing}")
        return tuple(by_handle[h] for h in level.source_handles)


def build_trace(micro_events: tuple[MicroEvent, ...], levels: tuple[CoarseGrainLevel, ...]) -> CoarseGrainedTrace:
    """Validate that every non-micro level's handles are all present in ``micro_events``."""
    known_handles = {e.handle for e in micro_events}
    for level in levels:
        if level.level == "micro":
            continue
        missing = [h for h in level.source_handles if h not in known_handles]
        if missing:
            raise ValueError(f"level '{level.level}' references unknown micro handles: {missing}")
    return CoarseGrainedTrace(micro_events, levels)
