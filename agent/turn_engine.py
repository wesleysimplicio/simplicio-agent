"""TurnEngine — máquina de estados explícita para um turno.

Mantém AIAgent como fachada pública compatível. Este módulo NÃO reescreve
o conversation_loop; only formaliza as transições válidas de um turno para que
cancelamento, retry, compressão e retomada deixem de competir por flags soltas.

Fases (TurnPhase):
    ACCEPTED -> STARTED -> TOOL_CALL <-> TOOL_RESULT -> FINALIZE -> COMPLETED
                                  \\-> COMPRESS -> TOOL_CALL
    Qualquer fase -> CANCELLED
    Qualquer fase -> FAILED (exceto COMPLETED/CANCELLED)

Invariantes:
    - transições inválidas levantam TurnTransitionError;
    - CANCELLED/FAILED/COMPLETED são estados terminais (não saem);
    - TOOL_CALL <-> TOOL_RESULT é o laço de ferramentas;
    - COMPRESS só é alcançável a partir de TOOL_CALL/TOOL_RESULT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from agent.mapper_adapter import ContextSnapshotHandle, CausalScope


class TurnPhase(str, Enum):
    ACCEPTED = "accepted"
    STARTED = "started"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    COMPRESS = "compress"
    FINALIZE = "finalize"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnTransitionError(Exception):
    """Levantado quando uma transição de fase não é permitida."""


# Transições permitidas: de -> conjunto de destinos.
_ALLOWED: dict[TurnPhase, set[TurnPhase]] = {
    TurnPhase.ACCEPTED: {
        TurnPhase.STARTED,
        TurnPhase.TOOL_CALL,
        TurnPhase.CANCELLED,
        TurnPhase.FAILED,
    },
    TurnPhase.STARTED: {TurnPhase.TOOL_CALL, TurnPhase.FINALIZE, TurnPhase.CANCELLED, TurnPhase.FAILED},
    TurnPhase.TOOL_CALL: {
        TurnPhase.TOOL_RESULT,
        TurnPhase.COMPRESS,
        TurnPhase.FINALIZE,
        TurnPhase.CANCELLED,
        TurnPhase.FAILED,
    },
    TurnPhase.TOOL_RESULT: {
        TurnPhase.TOOL_CALL,
        TurnPhase.COMPRESS,
        TurnPhase.FINALIZE,
        TurnPhase.CANCELLED,
        TurnPhase.FAILED,
    },
    TurnPhase.COMPRESS: {TurnPhase.TOOL_CALL, TurnPhase.CANCELLED, TurnPhase.FAILED},
    TurnPhase.FINALIZE: {TurnPhase.COMPLETED, TurnPhase.CANCELLED, TurnPhase.FAILED},
    # Estados terminais não saem.
    TurnPhase.COMPLETED: set(),
    TurnPhase.FAILED: set(),
    TurnPhase.CANCELLED: set(),
}

_TERMINAL = {TurnPhase.COMPLETED, TurnPhase.FAILED, TurnPhase.CANCELLED}


@dataclass(frozen=True)
class CognitiveContext:
    """The causal ContextSnapshot value attached to a live turn."""

    snapshot_handle: Optional[ContextSnapshotHandle] = None
    reason_code: str = "NO_SNAPSHOT"

    @property
    def snapshot_id(self) -> Optional[str]:
        return self.snapshot_handle.snapshot_id if self.snapshot_handle else None

    @classmethod
    def for_turn(
        cls,
        agent: object,
        *,
        session_id: str,
        turn_id: str,
        attempt_id: str,
    ) -> "CognitiveContext":
        handle = getattr(agent, "_context_snapshot_handle", None)
        if handle is None:
            return cls()
        if not isinstance(handle, ContextSnapshotHandle):
            return cls(reason_code="INVALID_SNAPSHOT_HANDLE")
        expected_scope = CausalScope(
            session_id=session_id or "session",
            turn_id=turn_id,
            attempt_id=attempt_id or "0",
        )
        if handle.causal_scope != expected_scope:
            return cls(reason_code="SNAPSHOT_SCOPE_MISMATCH")
        return cls(snapshot_handle=handle, reason_code="SNAPSHOT_PINNED")


@dataclass
class TurnContext:
    """Identidade e bookkeeping de um turno (correlação, tentativa, cancelamento)."""

    turn_id: str
    attempt_id: str = "0"
    session_id: str = ""
    phase: TurnPhase = TurnPhase.ACCEPTED
    cancelled: bool = False
    history: List[TurnPhase] = field(default_factory=list)
    cognitive_context: CognitiveContext = field(default_factory=CognitiveContext)

    @property
    def is_terminal(self) -> bool:
        return self.phase in _TERMINAL


class TurnEngine:
    """Valida e aplica transições de fase para um TurnContext."""

    @staticmethod
    def can_transition(ctx: TurnContext, target: TurnPhase) -> bool:
        if ctx.phase in _TERMINAL:
            return False
        return target in _ALLOWED.get(ctx.phase, set())

    @classmethod
    def transition(cls, ctx: TurnContext, target: TurnPhase) -> TurnPhase:
        if cls.can_transition(ctx, target):
            ctx.history.append(ctx.phase)
            ctx.phase = target
            if target is TurnPhase.CANCELLED:
                ctx.cancelled = True
            return target
        raise TurnTransitionError(
            f"transição inválida {ctx.phase.value} -> {target.value}"
        )

    @classmethod
    def cancel(cls, ctx: TurnContext) -> TurnPhase:
        """Cancelamento é válido a partir de qualquer fase não-terminal."""
        return cls.transition(ctx, TurnPhase.CANCELLED)

    @classmethod
    def fail(cls, ctx: TurnContext) -> TurnPhase:
        return cls.transition(ctx, TurnPhase.FAILED)


def mark_tool_call(ctx: TurnContext) -> TurnPhase:
    return TurnEngine.transition(ctx, TurnPhase.TOOL_CALL)


def mark_tool_result(ctx: TurnContext) -> TurnPhase:
    return TurnEngine.transition(ctx, TurnPhase.TOOL_RESULT)


def mark_compress(ctx: TurnContext) -> TurnPhase:
    return TurnEngine.transition(ctx, TurnPhase.COMPRESS)


def mark_finalize(ctx: TurnContext) -> TurnPhase:
    return TurnEngine.transition(ctx, TurnPhase.FINALIZE)


def mark_completed(ctx: TurnContext) -> TurnPhase:
    return TurnEngine.transition(ctx, TurnPhase.COMPLETED)
