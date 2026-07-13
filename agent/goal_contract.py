"""GoalContract/v1 — durable, honest goal state for the agent.

The goal contract is deliberately a small control-plane value object.  It
keeps the user's objective and acceptance criteria tamper-evident while the
agent adds facts, inferences, questions, and verification receipts over time.
Every update returns a new value, making a serialized value safe to resume
after a process restart without silently changing the original objective.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Optional


GOAL_CONTRACT_SCHEMA = "simplicio.goal-contract"
GOAL_CONTRACT_SCHEMA_VERSION = "simplicio.goal-contract/v1"
GOAL_CONTRACT_VERSION = GOAL_CONTRACT_SCHEMA_VERSION


class GoalState(str, Enum):
    """Lifecycle states; completion claims are intentionally explicit."""

    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED_VERIFIED = "completed_verified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Names used by early callers are retained as harmless aliases.
GoalStatus = GoalState
TerminalState = GoalState
TERMINAL_STATES = frozenset({
    GoalState.COMPLETED_VERIFIED,
    GoalState.COMPLETED_UNVERIFIED,
    GoalState.FAILED,
    GoalState.CANCELLED,
})


class GoalContractError(ValueError):
    """Base error for malformed or dishonest goal contracts."""


class InvalidGoalTransition(GoalContractError):
    """Raised when a goal state transition is not permitted."""


class VerificationRequiredError(GoalContractError):
    """Raised when ``completed_verified`` lacks required proof."""


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_tuple(values: Optional[Iterable[Any]]) -> tuple[Any, ...]:
    return tuple(values or ())


@dataclass(frozen=True)
class Fact:
    """An observed fact, with optional provenance and confidence."""

    text: str
    source: str = ""
    confidence: Optional[float] = None

    @property
    def statement(self) -> str:
        return self.text

    def __post_init__(self) -> None:
        if not _clean_text(self.text):
            raise ValueError("fact text must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("fact confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"text": self.text}
        if self.source:
            result["source"] = self.source
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "Fact":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping):
            raise ValueError("fact must be a string or object")
        return cls(
            text=_clean_text(
                value.get("text", value.get("statement", value.get("fact")))
            ),
            source=_clean_text(value.get("source", value.get("source_ref"))),
            confidence=(
                float(value["confidence"])
                if value.get("confidence") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class Inference:
    """A conclusion derived from one or more facts."""

    text: str
    basis: tuple[str, ...] = ()
    confidence: Optional[float] = None

    @property
    def conclusion(self) -> str:
        return self.text

    def __post_init__(self) -> None:
        if not _clean_text(self.text):
            raise ValueError("inference text must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("inference confidence must be between 0 and 1")
        object.__setattr__(
            self, "basis", tuple(_clean_text(v) for v in self.basis if _clean_text(v))
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"text": self.text}
        if self.basis:
            result["basis"] = list(self.basis)
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "Inference":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping):
            raise ValueError("inference must be a string or object")
        basis = value.get("basis", value.get("based_on", ()))
        if isinstance(basis, str):
            basis = (basis,)
        return cls(
            text=_clean_text(
                value.get("text", value.get("conclusion", value.get("inference")))
            ),
            basis=tuple(basis or ()),
            confidence=(
                float(value["confidence"])
                if value.get("confidence") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class OpenQuestion:
    """An unresolved question; blocking questions prevent verified closure."""

    text: str
    blocking: bool = False

    @property
    def question(self) -> str:
        return self.text

    def __post_init__(self) -> None:
        if not _clean_text(self.text):
            raise ValueError("open question text must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "blocking": self.blocking}

    @classmethod
    def from_dict(cls, value: Any) -> "OpenQuestion":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping):
            raise ValueError("open question must be a string or object")
        return cls(
            text=_clean_text(value.get("text", value.get("question"))),
            blocking=bool(value.get("blocking", False)),
        )


@dataclass(frozen=True)
class Evidence:
    """A durable verification receipt or reference."""

    reference: str
    kind: str = ""
    verified: bool = True
    watcher_id: str = ""

    @property
    def ref(self) -> str:
        return self.reference

    def __post_init__(self) -> None:
        if not _clean_text(self.reference):
            raise ValueError("evidence reference must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "reference": self.reference,
            "verified": self.verified,
        }
        if self.kind:
            result["kind"] = self.kind
        if self.watcher_id:
            result["watcher_id"] = self.watcher_id
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "Evidence":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping):
            raise ValueError("evidence must be a string or object")
        return cls(
            reference=_clean_text(
                value.get("reference", value.get("ref", value.get("evidence")))
            ),
            kind=_clean_text(value.get("kind", value.get("type"))),
            verified=bool(value.get("verified", True)),
            watcher_id=_clean_text(value.get("watcher_id", value.get("watcher"))),
        )


@dataclass(frozen=True)
class WatcherRequirement:
    """A watcher gate that must be recomputed before verified completion."""

    name: str
    required: bool = True
    satisfied: bool = False
    receipt: str = ""
    recomputed: Optional[bool] = None

    @property
    def watcher(self) -> str:
        return self.name

    @property
    def is_satisfied(self) -> bool:
        return self.satisfied and (self.recomputed is not False)

    def __post_init__(self) -> None:
        if not _clean_text(self.name):
            raise ValueError("watcher name must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "satisfied": self.satisfied,
            "receipt": self.receipt,
            "recomputed": self.recomputed,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "WatcherRequirement":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping):
            raise ValueError("watcher requirement must be a string or object")
        return cls(
            name=_clean_text(
                value.get("name", value.get("watcher", value.get("requirement")))
            ),
            required=bool(value.get("required", True)),
            satisfied=bool(value.get("satisfied", value.get("passed", False))),
            receipt=_clean_text(value.get("receipt", value.get("evidence_ref"))),
            recomputed=(
                bool(value["recomputed"])
                if value.get("recomputed") is not None
                else None
            ),
        )


# Friendly aliases for consumers that prefer explicit names.
GoalFact = Fact
GoalInference = Inference
GoalOpenQuestion = OpenQuestion
StructuredFact = Fact
StructuredInference = Inference
VerificationEvidence = Evidence
WatcherGate = WatcherRequirement


@dataclass(frozen=True)
class GoalContract:
    """Immutable, resumable goal contract.

    ``objective`` and ``acceptance_criteria`` are immutable by construction,
    and their hashes are recomputed from canonical JSON on every access.  A
    caller may only evolve a contract through methods returning a new value.
    """

    objective: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    facts: tuple[Fact, ...] = ()
    inferences: tuple[Inference, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    watchers: tuple[WatcherRequirement, ...] = ()
    state: GoalState = GoalState.ACTIVE
    contract_id: str = ""
    created_at_ns: int = 0
    updated_at_ns: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        objective = _clean_text(self.objective)
        if not objective:
            raise ValueError("objective must be non-empty")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(
            self,
            "acceptance_criteria",
            tuple(_clean_text(v) for v in self.acceptance_criteria if _clean_text(v)),
        )
        object.__setattr__(
            self,
            "facts",
            tuple(v if isinstance(v, Fact) else Fact.from_dict(v) for v in self.facts),
        )
        object.__setattr__(
            self,
            "inferences",
            tuple(
                v if isinstance(v, Inference) else Inference.from_dict(v)
                for v in self.inferences
            ),
        )
        object.__setattr__(
            self,
            "open_questions",
            tuple(
                v if isinstance(v, OpenQuestion) else OpenQuestion.from_dict(v)
                for v in self.open_questions
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(
                v if isinstance(v, Evidence) else Evidence.from_dict(v)
                for v in self.evidence
            ),
        )
        object.__setattr__(
            self,
            "watchers",
            tuple(
                v
                if isinstance(v, WatcherRequirement)
                else WatcherRequirement.from_dict(v)
                for v in self.watchers
            ),
        )
        if not isinstance(self.state, GoalState):
            object.__setattr__(self, "state", GoalState(self.state))
        if not self.contract_id:
            object.__setattr__(self, "contract_id", uuid.uuid4().hex)
        now = time.time_ns()
        if not self.created_at_ns:
            object.__setattr__(self, "created_at_ns", now)
        if not self.updated_at_ns:
            object.__setattr__(self, "updated_at_ns", self.created_at_ns)
        if (
            self.state is GoalState.COMPLETED_VERIFIED
            and not self.can_complete_verified()
        ):
            raise VerificationRequiredError(
                "completed_verified requires verified evidence, satisfied watchers, and no blocking open questions"
            )

    @classmethod
    def create(
        cls,
        objective: str,
        acceptance_criteria: Iterable[str] = (),
        *,
        acceptance: Optional[Iterable[str]] = None,
        **kwargs: Any,
    ) -> "GoalContract":
        if acceptance is not None:
            acceptance_criteria = acceptance
        return cls(
            objective=objective,
            acceptance_criteria=tuple(acceptance_criteria),
            **kwargs,
        )

    @property
    def objective_hash(self) -> str:
        return _canonical_hash(self.objective)

    @property
    def acceptance_criteria_hash(self) -> str:
        return _canonical_hash(list(self.acceptance_criteria))

    @property
    def ac_hash(self) -> str:
        return self.acceptance_criteria_hash

    @property
    def objective_sha256(self) -> str:
        return self.objective_hash

    @property
    def acceptance_criteria_sha256(self) -> str:
        return self.acceptance_criteria_hash

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(item.reference for item in self.evidence)

    @property
    def watcher_requirements(self) -> tuple[WatcherRequirement, ...]:
        return self.watchers

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def status(self) -> str:
        """String status convenience for JSON/UI consumers."""
        return self.state.value

    @property
    def schema_version(self) -> str:
        return GOAL_CONTRACT_SCHEMA_VERSION

    @property
    def is_complete(self) -> bool:
        return self.state in {
            GoalState.COMPLETED_VERIFIED,
            GoalState.COMPLETED_UNVERIFIED,
        }

    @property
    def required_watchers_satisfied(self) -> bool:
        return all(w.is_satisfied for w in self.watchers if w.required)

    @property
    def has_verified_evidence(self) -> bool:
        return bool(self.evidence) and all(item.verified for item in self.evidence)

    def can_complete_verified(self) -> bool:
        return (
            self.has_verified_evidence
            and self.required_watchers_satisfied
            and not any(q.blocking for q in self.open_questions)
        )

    def _updated(self, **changes: Any) -> "GoalContract":
        changes.setdefault("updated_at_ns", time.time_ns())
        return replace(self, **changes)

    def add_fact(
        self, fact: Fact | str, *, source: str = "", confidence: Optional[float] = None
    ) -> "GoalContract":
        item = (
            fact
            if isinstance(fact, Fact)
            else Fact(fact, source=source, confidence=confidence)
        )
        return self._updated(facts=self.facts + (item,))

    def add_inference(
        self,
        inference: Inference | str,
        *,
        basis: Iterable[str] = (),
        confidence: Optional[float] = None,
    ) -> "GoalContract":
        item = (
            inference
            if isinstance(inference, Inference)
            else Inference(inference, tuple(basis), confidence)
        )
        return self._updated(inferences=self.inferences + (item,))

    def add_open_question(
        self, question: OpenQuestion | str, *, blocking: bool = False
    ) -> "GoalContract":
        item = (
            question
            if isinstance(question, OpenQuestion)
            else OpenQuestion(question, blocking=blocking)
        )
        return self._updated(open_questions=self.open_questions + (item,))

    def add_evidence(
        self,
        evidence: Evidence | str,
        *,
        kind: str = "",
        verified: bool = True,
        watcher_id: str = "",
    ) -> "GoalContract":
        item = (
            evidence
            if isinstance(evidence, Evidence)
            else Evidence(evidence, kind=kind, verified=verified, watcher_id=watcher_id)
        )
        return self._updated(evidence=self.evidence + (item,))

    record_evidence = add_evidence

    def add_watcher(
        self, watcher: WatcherRequirement | str, *, required: bool = True
    ) -> "GoalContract":
        item = (
            watcher
            if isinstance(watcher, WatcherRequirement)
            else WatcherRequirement(watcher, required=required)
        )
        return self._updated(watchers=self.watchers + (item,))

    require_watcher = add_watcher

    def satisfy_watcher(
        self, name: str, *, receipt: str = "", recomputed: bool = True
    ) -> "GoalContract":
        updated = tuple(
            replace(
                w, satisfied=True, receipt=receipt or w.receipt, recomputed=recomputed
            )
            if w.name == name
            else w
            for w in self.watchers
        )
        if not any(w.name == name for w in self.watchers):
            raise KeyError(name)
        return self._updated(watchers=updated)

    def transition(self, state: GoalState | str, *, reason: str = "") -> "GoalContract":
        target = state if isinstance(state, GoalState) else GoalState(state)
        if target is self.state:
            return self
        allowed = {
            GoalState.ACTIVE: {
                GoalState.PAUSED,
                GoalState.BLOCKED,
                GoalState.COMPLETED_VERIFIED,
                GoalState.COMPLETED_UNVERIFIED,
                GoalState.FAILED,
                GoalState.CANCELLED,
            },
            GoalState.PAUSED: {
                GoalState.ACTIVE,
                GoalState.BLOCKED,
                GoalState.CANCELLED,
            },
            GoalState.BLOCKED: {
                GoalState.ACTIVE,
                GoalState.FAILED,
                GoalState.CANCELLED,
            },
        }
        if target is GoalState.COMPLETED_VERIFIED and not self.can_complete_verified():
            raise VerificationRequiredError(
                "completed_verified requires verified evidence, satisfied watchers, and no blocking open questions"
            )
        if self.state not in allowed or target not in allowed[self.state]:
            raise InvalidGoalTransition(
                f"invalid goal transition {self.state.value!r} -> {target.value!r}"
            )
        return self._updated(state=target, reason=_clean_text(reason))

    def mark_completed_verified(self, *, reason: str = "") -> "GoalContract":
        return self.transition(GoalState.COMPLETED_VERIFIED, reason=reason)

    complete_verified = mark_completed_verified

    def mark_completed_unverified(self, *, reason: str = "") -> "GoalContract":
        return self.transition(GoalState.COMPLETED_UNVERIFIED, reason=reason)

    complete_unverified = mark_completed_unverified

    def resume(self) -> "GoalContract":
        if self.state not in {GoalState.PAUSED, GoalState.BLOCKED}:
            return self
        return self.transition(GoalState.ACTIVE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOAL_CONTRACT_SCHEMA,
            "schema_version": GOAL_CONTRACT_SCHEMA_VERSION,
            "contract_id": self.contract_id,
            "objective": self.objective,
            "objective_hash": self.objective_hash,
            "acceptance_criteria": list(self.acceptance_criteria),
            "acceptance_criteria_hash": self.acceptance_criteria_hash,
            "facts": [v.to_dict() for v in self.facts],
            "inferences": [v.to_dict() for v in self.inferences],
            "open_questions": [v.to_dict() for v in self.open_questions],
            "evidence": [v.to_dict() for v in self.evidence],
            "watchers": [v.to_dict() for v in self.watchers],
            "state": self.state.value,
            "reason": self.reason,
            "created_at_ns": self.created_at_ns,
            "updated_at_ns": self.updated_at_ns,
        }

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
        )

    # Explicit names make persistence call sites self-documenting.
    to_resume_dict = to_dict
    to_resume_json = to_json

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GoalContract":
        if not isinstance(data, Mapping):
            raise ValueError("goal contract must be an object")
        version = data.get(
            "schema_version", data.get("version", GOAL_CONTRACT_SCHEMA_VERSION)
        )
        if version != GOAL_CONTRACT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {version!r}; expected {GOAL_CONTRACT_SCHEMA_VERSION!r}"
            )
        objective = _clean_text(data.get("objective"))
        criteria = tuple(
            _clean_text(v)
            for v in data.get("acceptance_criteria", data.get("acceptance", ()))
            if _clean_text(v)
        )
        expected_objective_hash = data.get("objective_hash")
        expected_ac_hash = data.get("acceptance_criteria_hash", data.get("ac_hash"))
        if expected_objective_hash and expected_objective_hash != _canonical_hash(
            objective
        ):
            raise GoalContractError(
                "objective hash does not match serialized objective"
            )
        if expected_ac_hash and expected_ac_hash != _canonical_hash(list(criteria)):
            raise GoalContractError(
                "acceptance criteria hash does not match serialized criteria"
            )
        return cls(
            objective=objective,
            acceptance_criteria=criteria,
            facts=tuple(Fact.from_dict(v) for v in data.get("facts", ())),
            inferences=tuple(
                Inference.from_dict(v) for v in data.get("inferences", ())
            ),
            open_questions=tuple(
                OpenQuestion.from_dict(v)
                for v in data.get("open_questions", data.get("questions", ()))
            ),
            evidence=tuple(Evidence.from_dict(v) for v in data.get("evidence", ())),
            watchers=tuple(
                WatcherRequirement.from_dict(v)
                for v in data.get("watchers", data.get("watcher_requirements", ()))
            ),
            state=GoalState(data.get("state", GoalState.ACTIVE.value)),
            contract_id=_clean_text(data.get("contract_id")),
            created_at_ns=int(data.get("created_at_ns", 0) or 0),
            updated_at_ns=int(data.get("updated_at_ns", 0) or 0),
            reason=_clean_text(data.get("reason")),
        )

    @classmethod
    def from_json(cls, text: str) -> "GoalContract":
        return cls.from_dict(json.loads(text))

    from_resume_dict = from_dict
    from_resume_json = from_json

    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())


__all__ = [
    "GOAL_CONTRACT_SCHEMA",
    "GOAL_CONTRACT_SCHEMA_VERSION",
    "GOAL_CONTRACT_VERSION",
    "GoalState",
    "GoalStatus",
    "TerminalState",
    "TERMINAL_STATES",
    "GoalContractError",
    "InvalidGoalTransition",
    "VerificationRequiredError",
    "Fact",
    "Inference",
    "OpenQuestion",
    "Evidence",
    "WatcherRequirement",
    "GoalFact",
    "GoalInference",
    "GoalOpenQuestion",
    "StructuredFact",
    "StructuredInference",
    "VerificationEvidence",
    "WatcherGate",
    "GoalContract",
]
