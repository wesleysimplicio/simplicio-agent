"""Versioned AgentHost discovery and bounded advisory replay.

This module is intentionally product-neutral.  Consumers discover the agent
host through a small, versioned contract; the host does not import or name any
particular client application.  Advisories are fixed, operational signals --
never arbitrary model output, prompts, workspace contents, or secrets.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Final

from agent.protocol_v1 import PROTOCOL_VERSION as AGENT_PROTOCOL_VERSION

HOST_PROTOCOL_SCHEMA: Final = "simplicio.agent-host/v1"
HOST_PROTOCOL_VERSION: Final = 1
ADVISORY_SCHEMA: Final = "simplicio.agent-advisory/v1"

# Keep this list limited to operations the daemon actually implements.  A
# client may safely fail closed when one of its required capabilities is absent.
HOST_CAPABILITIES: Final = (
    "host.advisories",
    "host.status",
    "invalidate",
    "ping",
    "shutdown",
    "turn.start",
)

_ADVISORY_CATALOG: Final[dict[str, tuple[str, str, str | None]]] = {
    "host.ready": ("info", "Agent host is ready.", None),
    "host.backpressure": ("warning", "Agent host is saturated.", "retry"),
    "host.draining": ("warning", "Agent host is draining.", None),
    "turn.completed": ("info", "Agent turn completed.", None),
    "turn.failed": ("warning", "Agent turn failed.", "inspect_logs"),
}


def host_protocol_metadata(profile: str) -> dict[str, Any]:
    """Return the stable discovery envelope included in every host response."""
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("profile must be a non-empty string")
    return {
        "protocol_schema": HOST_PROTOCOL_SCHEMA,
        "protocol_version": HOST_PROTOCOL_VERSION,
        "agent_protocol": AGENT_PROTOCOL_VERSION,
        "profile": profile,
        "capabilities": list(HOST_CAPABILITIES),
        "advisory_schema": ADVISORY_SCHEMA,
    }


class HostAdvisoryBuffer:
    """Thread-safe, bounded replay buffer for generic host attention signals."""

    def __init__(self, *, max_events: int = 128) -> None:
        if (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or max_events < 1
        ):
            raise ValueError("max_events must be a positive integer")
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._sequence = 0
        self._lock = threading.Lock()

    def publish(self, kind: str) -> dict[str, Any]:
        """Publish one catalogued signal without accepting arbitrary payloads."""
        try:
            severity, summary, action = _ADVISORY_CATALOG[kind]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown advisory kind: {kind}") from exc

        with self._lock:
            self._sequence += 1
            event = {
                "schema": ADVISORY_SCHEMA,
                "sequence": self._sequence,
                "kind": kind,
                "severity": severity,
                "summary": summary,
                "action": action,
                "ts_wall_ns": time.time_ns(),
            }
            self._events.append(event)
            # Do not leak the mutable object retained by the buffer.
            return dict(event)

    def replay(self, *, after: int = 0) -> dict[str, Any]:
        """Return retained events after ``after`` and an idempotent cursor."""
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError("after must be a non-negative integer")

        with self._lock:
            if after > self._sequence:
                raise ValueError("after exceeds the current advisory sequence")
            retained = list(self._events)
            first_sequence = retained[0]["sequence"] if retained else self._sequence + 1
            truncated = bool(retained) and after < first_sequence - 1
            events = [dict(event) for event in retained if event["sequence"] > after]
            return {
                "schema": ADVISORY_SCHEMA,
                "events": events,
                "next_cursor": self._sequence,
                "truncated": truncated,
            }
