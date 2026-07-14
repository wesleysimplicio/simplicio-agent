"""Receipt-backed autobiographical consolidation with bounded disclosure."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b\s*[:=]\s*[^\s,;]+"
)


class MemoryScope(str, Enum):
    USER_PROJECT = "user_project"  # Isa
    RUNTIME_SELF = "runtime_self"  # Helo
    EXTERNAL = "external"  # Levi acquisition boundary


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(frozen=True)
class CausalEvidence:
    prediction_receipt: str
    outcome_receipt: str
    relation: str

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.prediction_receipt):
            raise ValueError("prediction_receipt must be a sha256 reference")
        if not _SHA256.fullmatch(self.outcome_receipt):
            raise ValueError("outcome_receipt must be a sha256 reference")
        if not self.relation.strip():
            raise ValueError("causal relation must be declared")


@dataclass(frozen=True)
class EpisodeFact:
    key: str
    summary: str
    kind: MemoryKind
    evidence: CausalEvidence
    confidence: float
    personal: bool = False
    user_preference: bool = False
    consent_receipt: str = ""
    poisoned_source: bool = False

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.summary.strip():
            raise ValueError("episode fact key and summary must be non-empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.consent_receipt and not _SHA256.fullmatch(self.consent_receipt):
            raise ValueError("consent_receipt must be a sha256 reference")


@dataclass(frozen=True)
class EpisodeManifest:
    episode_id: str
    scope: MemoryScope
    completed_verified: bool
    valid_from: int
    facts: tuple[EpisodeFact, ...]

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise ValueError("episode_id must be non-empty")
        object.__setattr__(self, "facts", tuple(self.facts))


@dataclass(frozen=True)
class AutobiographicalMemory:
    memory_id: str
    key: str
    summary: str
    kind: MemoryKind
    scope: MemoryScope
    confidence: float
    provenance: tuple[str, ...]
    valid_from: int
    system_time: int
    revoked_at: int | None = None
    supersedes: str = ""

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class RecallResult:
    memories: tuple[AutobiographicalMemory, ...]

    @property
    def known(self) -> bool:
        return bool(self.memories)


def sanitize_evidence(text: str) -> str:
    """Redact common direct identifiers and secret assignments before storage."""
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", text)
    return _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)


class AutobiographicalStore:
    """Small governed store; raw transcripts are deliberately not accepted."""

    def __init__(self, memories: Iterable[AutobiographicalMemory] = ()) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}

    @property
    def memories(self) -> tuple[AutobiographicalMemory, ...]:
        return tuple(self._memories[key] for key in sorted(self._memories))

    def consolidate(
        self, manifest: EpisodeManifest, *, system_time: int
    ) -> tuple[AutobiographicalMemory, ...]:
        if not manifest.completed_verified or manifest.scope is MemoryScope.EXTERNAL:
            return ()

        promoted: list[AutobiographicalMemory] = []
        for index, fact in enumerate(manifest.facts):
            if fact.poisoned_source:
                continue
            if manifest.scope is MemoryScope.RUNTIME_SELF and fact.personal:
                continue
            if fact.user_preference and not fact.consent_receipt:
                continue
            if fact.kind is MemoryKind.PROCEDURAL and not manifest.completed_verified:
                continue

            current = self._active_for(manifest.scope, fact.key)
            memory_id = f"{manifest.episode_id}:{index}"
            memory = AutobiographicalMemory(
                memory_id=memory_id,
                key=fact.key,
                summary=sanitize_evidence(fact.summary),
                kind=fact.kind,
                scope=manifest.scope,
                confidence=fact.confidence,
                provenance=(
                    fact.evidence.prediction_receipt,
                    fact.evidence.outcome_receipt,
                    *((fact.consent_receipt,) if fact.consent_receipt else ()),
                ),
                valid_from=manifest.valid_from,
                system_time=system_time,
                supersedes=current.memory_id if current else "",
            )
            if current is not None:
                self._memories[current.memory_id] = replace(
                    current, revoked_at=system_time
                )
            self._memories[memory_id] = memory
            promoted.append(memory)
        return tuple(promoted)

    def recall(self, key: str, *, scope: MemoryScope) -> RecallResult:
        matches = tuple(
            memory
            for memory in self.memories
            if memory.key == key and memory.scope is scope and memory.active
        )
        return RecallResult(matches)

    def revoke(self, memory_id: str, *, system_time: int) -> AutobiographicalMemory:
        memory = self._memories[memory_id]
        revoked = replace(memory, revoked_at=system_time)
        self._memories[memory_id] = revoked
        return revoked

    def _active_for(
        self, scope: MemoryScope, key: str
    ) -> AutobiographicalMemory | None:
        for memory in self._memories.values():
            if memory.scope is scope and memory.key == key and memory.active:
                return memory
        return None
