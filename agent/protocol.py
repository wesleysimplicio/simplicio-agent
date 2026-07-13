"""Stable typed protocol boundary for agents hosted by the shared lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, TypedDict, cast, runtime_checkable


class AgentConversationResult(TypedDict, total=False):
    """Minimal stable result shape returned by ``run_conversation``.

    ``AIAgent`` returns additional fields in some paths. The host boundary only
    relies on this narrow, backwards-compatible subset.
    """

    final_response: str | None
    messages: list[dict[str, Any]]
    api_calls: int
    completed: bool
    failed: bool
    interrupted: bool
    error: str


class SessionSnapshot(TypedDict):
    """Visible session state exported by ``AgentHost.status()``."""

    profile: str
    session_id: str
    incarnation: str
    revision: int
    active_leases: int


class HostStatusSnapshot(TypedDict):
    """Small status envelope surfaces can relay without host internals."""

    ready: bool
    stopping: bool
    sessions: list[SessionSnapshot]


@dataclass(frozen=True, slots=True)
class HostTurnRequest:
    """Typed host request for one turn on one long-lived session identity."""

    profile: str
    session_id: str
    user_message: str
    idempotency_key: str | None = None
    incarnation: str = "default"
    revision: int = 0
    conversation_kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile:
            raise ValueError("profile is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        object.__setattr__(
            self,
            "conversation_kwargs",
            dict(self.conversation_kwargs),
        )

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        default_profile: str,
    ) -> "HostTurnRequest":
        """Normalize daemon/UI payloads into the host boundary contract."""

        conversation_kwargs = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "op",
                "profile",
                "session_id",
                "message",
                "user_message",
                "idempotency_key",
                "incarnation",
                "revision",
                "timeout",
            }
        }
        return cls(
            profile=str(payload.get("profile", default_profile)),
            session_id=str(payload["session_id"]),
            user_message=str(payload.get("message", payload.get("user_message", ""))),
            idempotency_key=cast(str | None, payload.get("idempotency_key")),
            incarnation=str(payload.get("incarnation", "default")),
            revision=int(payload.get("revision", 0)),
            conversation_kwargs=conversation_kwargs,
        )


@runtime_checkable
class AgentProtocol(Protocol):
    """Minimum conversation contract required by :class:`agent.host.AgentHost`.

    ``AIAgent`` remains the public implementation, while this structural
    contract lets the host work with compatible facades without importing or
    owning the concrete agent class.
    """

    def run_conversation(
        self,
        user_message: str,
        **kwargs: Any,
    ) -> AgentConversationResult:
        """Run one conversation turn and return the implementation result."""


__all__ = [
    "AgentConversationResult",
    "AgentProtocol",
    "HostStatusSnapshot",
    "HostTurnRequest",
    "SessionSnapshot",
]
