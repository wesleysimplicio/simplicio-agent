"""Stable session/turn boundary for the modular ``AIAgent`` architecture.

This module is deliberately a small contract seam.  It composes identity,
prompt/toolset fingerprints, provider route, operational cognition, and bridge
generation without owning any of those implementations.  ``AIAgent`` remains
the public facade and existing callers are not wired to this class yet; a
later integration slice can adopt it behind a compatibility adapter.

The important invariant is that a session incarnation has one immutable
snapshot.  A changed prompt, toolset, provider route, cognition digest, or
bridge generation therefore cannot silently reuse the same prefix-cache and
capability identity.  Turn execution itself remains owned by
:class:`agent.turn_engine.TurnEngine`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional

from agent.self_model import SelfModelSnapshot
from agent.turn_engine import TurnContext, TurnEngine, TurnPhase


SESSION_SCHEMA = "simplicio.agent.session/v1"


class SessionInvariantError(ValueError):
    """Raised when a session or turn violates its immutable boundary."""


def _required_text(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value:
        raise SessionInvariantError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Stable identity for one profile/session incarnation."""

    profile: str
    session_id: str
    incarnation: str = "default"
    revision: int = 0

    def __post_init__(self) -> None:
        for name in ("profile", "session_id", "incarnation"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if self.revision < 0:
            raise SessionInvariantError("revision must be >= 0")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _toolset_fingerprint(tool_names: Iterable[str]) -> str:
    names = tuple(sorted({_required_text(name, "tool name") for name in tool_names}))
    return _fingerprint("\n".join(names))


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Non-secret, immutable identity of a session incarnation.

    Raw system prompts and tool definitions are intentionally not retained;
    only fingerprints cross this boundary.  ``cognition_digest`` is supplied
    by the measured :class:`SelfModelSnapshot` when available.
    """

    identity: SessionIdentity
    system_prompt_hash: str
    toolset_hash: str
    provider_route: str
    cognition_digest: str = ""
    bridge_generation: Optional[int] = None
    schema: str = SESSION_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SessionIdentity):
            raise TypeError("identity must be a SessionIdentity")
        for name in ("system_prompt_hash", "toolset_hash", "provider_route"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if self.cognition_digest:
            object.__setattr__(
                self,
                "cognition_digest",
                _required_text(self.cognition_digest, "cognition_digest"),
            )
        if self.bridge_generation is not None and self.bridge_generation < 0:
            raise SessionInvariantError("bridge_generation must be >= 0")

    @classmethod
    def from_parts(
        cls,
        identity: SessionIdentity,
        *,
        system_prompt: str,
        tool_names: Iterable[str],
        provider_route: str,
        cognition: SelfModelSnapshot | None = None,
        bridge_generation: int | None = None,
    ) -> "SessionSnapshot":
        """Build a snapshot without retaining prompt, tools, or secrets."""

        if not isinstance(identity, SessionIdentity):
            raise TypeError("identity must be a SessionIdentity")
        system_prompt = _required_text(system_prompt, "system_prompt")
        return cls(
            identity=identity,
            system_prompt_hash=_fingerprint(system_prompt),
            toolset_hash=_toolset_fingerprint(tool_names),
            provider_route=_required_text(provider_route, "provider_route"),
            cognition_digest=cognition.digest() if cognition is not None else "",
            bridge_generation=bridge_generation,
        )

    def assert_compatible(
        self,
        *,
        system_prompt: str,
        tool_names: Iterable[str],
        provider_route: str,
        cognition: SelfModelSnapshot | None = None,
        bridge_generation: int | None = None,
    ) -> None:
        """Reject any attempt to mutate this incarnation's identity."""

        candidate = SessionSnapshot.from_parts(
            self.identity,
            system_prompt=system_prompt,
            tool_names=tool_names,
            provider_route=provider_route,
            cognition=cognition,
            bridge_generation=bridge_generation,
        )
        if candidate != self:
            raise SessionInvariantError(
                "session incarnation changed; open a new session instead"
            )


class AgentSession:
    """Bounded owner of one session incarnation's active turn set."""

    def __init__(self, snapshot: SessionSnapshot) -> None:
        if not isinstance(snapshot, SessionSnapshot):
            raise TypeError("snapshot must be a SessionSnapshot")
        self.snapshot = snapshot
        self._active: dict[str, TurnContext] = {}
        self._next_turn = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def active_turns(self) -> int:
        return len(self._active)

    def _require_active(self, context: TurnContext) -> TurnContext:
        if context.session_id != self.snapshot.identity.session_id:
            raise SessionInvariantError("turn belongs to another session")
        current = self._active.get(context.turn_id)
        if current is not context:
            raise SessionInvariantError("turn is not active in this session")
        if context.is_terminal:
            raise SessionInvariantError("turn is already terminal")
        return context

    def begin_turn(
        self, *, turn_id: str | None = None, attempt_id: str = "0"
    ) -> TurnContext:
        """Create and start one turn under this session identity."""

        if self._closed:
            raise SessionInvariantError("session is closed")
        self._next_turn += 1
        turn_id = turn_id or (
            f"{self.snapshot.identity.session_id}:turn-{self._next_turn}"
        )
        turn_id = _required_text(turn_id, "turn_id")
        if turn_id in self._active:
            raise SessionInvariantError("turn_id is already active")
        context = TurnContext(
            turn_id=turn_id,
            attempt_id=_required_text(attempt_id, "attempt_id"),
            session_id=self.snapshot.identity.session_id,
        )
        TurnEngine.transition(context, TurnPhase.STARTED)
        self._active[turn_id] = context
        return context

    def complete_turn(self, context: TurnContext) -> TurnContext:
        """Move a live turn through finalization to ``COMPLETED``."""

        context = self._require_active(context)
        if context.phase is TurnPhase.COMPRESS:
            TurnEngine.transition(context, TurnPhase.TOOL_CALL)
        if context.phase not in {
            TurnPhase.STARTED,
            TurnPhase.TOOL_CALL,
            TurnPhase.TOOL_RESULT,
        }:
            raise SessionInvariantError(
                f"cannot complete turn from {context.phase.value}"
            )
        TurnEngine.transition(context, TurnPhase.FINALIZE)
        TurnEngine.transition(context, TurnPhase.COMPLETED)
        self._active.pop(context.turn_id, None)
        return context

    def fail_turn(self, context: TurnContext) -> TurnContext:
        """Terminate a live turn as failed."""

        context = self._require_active(context)
        TurnEngine.fail(context)
        self._active.pop(context.turn_id, None)
        return context

    def cancel_turn(self, context: TurnContext) -> TurnContext:
        """Terminate a live turn as cancelled."""

        context = self._require_active(context)
        TurnEngine.cancel(context)
        self._active.pop(context.turn_id, None)
        return context

    def close(self) -> None:
        """Close an idle session; active turns must be resolved first."""

        if self._active:
            raise SessionInvariantError("cannot close a session with active turns")
        self._closed = True


__all__ = [
    "SESSION_SCHEMA",
    "AgentSession",
    "SessionIdentity",
    "SessionInvariantError",
    "SessionSnapshot",
]
