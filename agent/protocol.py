"""Stable protocol boundary for agents hosted by the shared lifecycle."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentProtocol(Protocol):
    """Minimum conversation contract required by :class:`agent.host.AgentHost`.

    ``AIAgent`` remains the public implementation, while this structural
    contract lets the host work with compatible facades without importing or
    owning the concrete agent class.
    """

    def run_conversation(self, user_message: str, **kwargs: Any) -> Any:
        """Run one conversation turn and return the implementation result."""


__all__ = ["AgentProtocol"]
