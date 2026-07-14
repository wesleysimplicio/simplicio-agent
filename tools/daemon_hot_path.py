"""Pure contract for the bounded daemon hot path.

The warm Python daemon and :class:`agent.host.AgentHost` remain the current
implementation.  This module freezes the observable boundary a future native
daemon can shadow-run: version negotiation, health classification, bounded
reconnect, crash isolation, and one-shot rollback planning.  It deliberately
does not create, supervise, or terminate processes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar


DAEMON_HOT_PATH_SCHEMA = "simplicio.agent-daemon-hot-path/v1"
DAEMON_PROTOCOL_VERSION = 1
_PROTOCOL_STATUSES = frozenset({"compatible", "incompatible", "unreported"})


class DaemonPhase(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


class DaemonEvent(str, Enum):
    START = "start"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DISCONNECTED = "disconnected"
    RECONNECT_SUCCEEDED = "reconnect_succeeded"
    RECONNECT_FAILED = "reconnect_failed"
    CRASHED = "crashed"
    ROLLBACK_REQUESTED = "rollback_requested"
    ROLLBACK_SUCCEEDED = "rollback_succeeded"
    ROLLBACK_FAILED = "rollback_failed"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"


def _non_negative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class DaemonStartup:
    """Versioned startup intent understood by both old and native daemons."""

    profile: str
    protocol_version: int = DAEMON_PROTOCOL_VERSION
    generation: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile:
            raise ValueError("profile is required")
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version < 1
        ):
            raise ValueError("protocol_version must be a positive integer")
        _non_negative_int("generation", self.generation)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": DAEMON_HOT_PATH_SCHEMA,
            "op": "startup",
            "profile": self.profile,
            "protocol_version": self.protocol_version,
            "generation": self.generation,
        }


@dataclass(frozen=True)
class DaemonHealth:
    """Stable health projection of the existing ``ping``/``status`` replies."""

    ready: bool
    protocol_status: str
    reason_code: str
    profile: str | None = None
    protocol_version: int | None = None
    host_ready: bool | None = None
    host_stopping: bool | None = None

    def __post_init__(self) -> None:
        if self.protocol_status not in _PROTOCOL_STATUSES:
            raise ValueError(f"invalid protocol_status: {self.protocol_status}")
        if not isinstance(self.ready, bool):
            raise TypeError("ready must be bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": DAEMON_HOT_PATH_SCHEMA,
            "ready": self.ready,
            "protocol_status": self.protocol_status,
            "reason_code": self.reason_code,
            "profile": self.profile,
            "protocol_version": self.protocol_version,
            "host_ready": self.host_ready,
            "host_stopping": self.host_stopping,
        }


def classify_health(
    response: Mapping[str, Any] | None,
    *,
    expected_profile: str,
    expected_protocol: int = DAEMON_PROTOCOL_VERSION,
) -> DaemonHealth:
    """Classify a daemon status response without trusting process presence.

    Existing daemon responses may not report a protocol version yet; those are
    explicitly ``unreported`` and therefore not ready.  This lets a caller
    shadow-run the contract without falsely claiming native compatibility.
    """

    if not isinstance(response, Mapping):
        return DaemonHealth(False, "unreported", "invalid_response")
    if response.get("ok") is not True:
        return DaemonHealth(False, "unreported", "daemon_error")

    raw_version = response.get("protocol_version")
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        protocol_status = "unreported"
    elif raw_version != expected_protocol:
        protocol_status = "incompatible"
    else:
        protocol_status = "compatible"

    profile = response.get("profile")
    if profile is not None and profile != expected_profile:
        return DaemonHealth(
            False, protocol_status, "profile_mismatch", str(profile), raw_version
        )
    if protocol_status != "compatible":
        return DaemonHealth(
            False,
            protocol_status,
            f"protocol_{protocol_status}",
            expected_profile,
            raw_version,
        )
    if response.get("pong") is False:
        return DaemonHealth(
            False, protocol_status, "ping_failed", expected_profile, raw_version
        )

    host = response.get("host")
    host_ready: bool | None = None
    host_stopping: bool | None = None
    if isinstance(host, Mapping):
        host_ready = host.get("ready") if isinstance(host.get("ready"), bool) else None
        host_stopping = (
            host.get("stopping") if isinstance(host.get("stopping"), bool) else None
        )
        if host_ready is False or host_stopping is True:
            return DaemonHealth(
                False,
                protocol_status,
                "host_not_ready",
                expected_profile,
                raw_version,
                host_ready,
                host_stopping,
            )
    return DaemonHealth(
        True,
        protocol_status,
        "ready",
        expected_profile,
        raw_version,
        host_ready,
        host_stopping,
    )


@dataclass(frozen=True)
class DaemonReconnectPolicy:
    """Small deterministic retry budget; execution belongs to the caller."""

    max_attempts: int = 3
    delays_ms: tuple[int, ...] = (100, 500, 1_000)

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        delays = tuple(self.delays_ms)
        if not delays or any(
            isinstance(delay, bool) or not isinstance(delay, int) or delay < 0
            for delay in delays
        ):
            raise ValueError("delays_ms must be a non-empty tuple of non-negative ints")
        object.__setattr__(self, "delays_ms", delays)


@dataclass(frozen=True)
class DaemonState:
    phase: DaemonPhase = DaemonPhase.STOPPED
    reconnect_attempts: int = 0
    generation: int = 0
    last_error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.phase, DaemonPhase):
            object.__setattr__(self, "phase", DaemonPhase(self.phase))
        _non_negative_int("reconnect_attempts", self.reconnect_attempts)
        _non_negative_int("generation", self.generation)
        if not isinstance(self.last_error, str):
            raise TypeError("last_error must be a string")

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "reconnect_attempts": self.reconnect_attempts,
            "generation": self.generation,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class DaemonDecision:
    phase: DaemonPhase
    state: DaemonState
    retry: bool
    retry_delay_ms: int | None
    reason: str
    protocol_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": DAEMON_HOT_PATH_SCHEMA,
            "phase": self.phase.value,
            "state": self.state.to_dict(),
            "retry": self.retry,
            "retry_delay_ms": self.retry_delay_ms,
            "reason": self.reason,
            "protocol_status": self.protocol_status,
        }


class DaemonHotPathController:
    """Pure reducer for startup, health, reconnect, crash, and stop events."""

    def __init__(self, policy: DaemonReconnectPolicy | None = None) -> None:
        self.policy = policy or DaemonReconnectPolicy()

    def step(
        self,
        state: DaemonState,
        event: DaemonEvent,
        *,
        protocol_status: str = "unreported",
        error: str = "",
    ) -> DaemonDecision:
        if not isinstance(state, DaemonState):
            raise TypeError("state must be a DaemonState")
        if not isinstance(event, DaemonEvent):
            event = DaemonEvent(event)
        if protocol_status not in _PROTOCOL_STATUSES:
            raise ValueError(f"invalid protocol_status: {protocol_status}")
        if not isinstance(error, str):
            raise TypeError("error must be a string")

        if event is DaemonEvent.START:
            return self._decision(
                DaemonPhase.STARTING,
                DaemonState(
                    DaemonPhase.STARTING, state.reconnect_attempts, state.generation
                ),
                False,
                None,
                "startup_requested",
                protocol_status,
            )
        if event is DaemonEvent.HEALTHY:
            if protocol_status != "compatible":
                return self._decision(
                    DaemonPhase.FAILED,
                    DaemonState(
                        DaemonPhase.FAILED,
                        state.reconnect_attempts,
                        state.generation,
                        error,
                    ),
                    False,
                    None,
                    "protocol_not_compatible",
                    protocol_status,
                )
            return self._decision(
                DaemonPhase.READY,
                DaemonState(DaemonPhase.READY, 0, state.generation, ""),
                False,
                None,
                "health_ready",
                protocol_status,
            )
        if event in {
            DaemonEvent.UNHEALTHY,
            DaemonEvent.DISCONNECTED,
            DaemonEvent.RECONNECT_FAILED,
            DaemonEvent.CRASHED,
        }:
            return self._retry_or_fail(state, protocol_status, error, event.value)
        if event is DaemonEvent.RECONNECT_SUCCEEDED:
            return self._decision(
                DaemonPhase.READY,
                DaemonState(DaemonPhase.READY, 0, state.generation + 1, ""),
                False,
                None,
                "reconnect_succeeded",
                protocol_status,
            )
        if event is DaemonEvent.ROLLBACK_REQUESTED:
            return self._decision(
                DaemonPhase.ROLLING_BACK,
                DaemonState(
                    DaemonPhase.ROLLING_BACK,
                    state.reconnect_attempts,
                    state.generation,
                    error,
                ),
                False,
                None,
                "rollback_requested",
                protocol_status,
            )
        if event is DaemonEvent.ROLLBACK_SUCCEEDED:
            return self._decision(
                DaemonPhase.ROLLED_BACK,
                DaemonState(DaemonPhase.ROLLED_BACK, 0, state.generation + 1, ""),
                False,
                None,
                "rollback_succeeded",
                protocol_status,
            )
        if event is DaemonEvent.ROLLBACK_FAILED:
            return self._decision(
                DaemonPhase.FAILED,
                DaemonState(
                    DaemonPhase.FAILED,
                    state.reconnect_attempts,
                    state.generation,
                    error,
                ),
                False,
                None,
                "rollback_failed",
                protocol_status,
            )
        if event is DaemonEvent.STOP_REQUESTED:
            return self._decision(
                DaemonPhase.STOPPED,
                DaemonState(
                    DaemonPhase.STOPPED, state.reconnect_attempts, state.generation, ""
                ),
                False,
                None,
                "stop_requested",
                protocol_status,
            )
        return self._decision(
            DaemonPhase.STOPPED,
            DaemonState(
                DaemonPhase.STOPPED, state.reconnect_attempts, state.generation, ""
            ),
            False,
            None,
            "stopped",
            protocol_status,
        )

    def _retry_or_fail(
        self, state: DaemonState, protocol_status: str, error: str, reason: str
    ) -> DaemonDecision:
        attempt = state.reconnect_attempts
        if attempt >= self.policy.max_attempts:
            return self._decision(
                DaemonPhase.FAILED,
                DaemonState(DaemonPhase.FAILED, attempt, state.generation, error),
                False,
                None,
                "reconnect_limit_exhausted",
                protocol_status,
            )
        next_attempt = attempt + 1
        delay = self.policy.delays_ms[min(attempt, len(self.policy.delays_ms) - 1)]
        return self._decision(
            DaemonPhase.RECONNECTING,
            DaemonState(
                DaemonPhase.RECONNECTING, next_attempt, state.generation, error
            ),
            True,
            delay,
            reason,
            protocol_status,
        )

    @staticmethod
    def _decision(
        phase: DaemonPhase,
        state: DaemonState,
        retry: bool,
        retry_delay_ms: int | None,
        reason: str,
        protocol_status: str,
    ) -> DaemonDecision:
        return DaemonDecision(
            phase, state, retry, retry_delay_ms, reason, protocol_status
        )


@dataclass(frozen=True)
class CrashReceipt:
    """Stable, secret-free representation of a worker crash."""

    isolated: bool
    error_type: str
    fallback: str = "cold"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": DAEMON_HOT_PATH_SCHEMA,
            "isolated": self.isolated,
            "error_type": self.error_type,
            "fallback": self.fallback,
        }


T = TypeVar("T")


def guarded_call(
    fn: Callable[..., T], *args: object, **kwargs: object
) -> tuple[T | None, CrashReceipt | None]:
    """Run one hot-path callback without letting worker exceptions escape."""

    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # process-level cancellation is owned elsewhere
        return None, CrashReceipt(True, type(exc).__name__)


@dataclass(frozen=True)
class DaemonRollbackPlan:
    """A bounded rollback decision; activation remains an external concern."""

    active_version: str
    previous_version: str | None
    protocol_compatible: bool
    allowed: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not self.active_version:
            raise ValueError("active_version is required")
        if self.previous_version == self.active_version:
            raise ValueError("previous_version must differ from active_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": DAEMON_HOT_PATH_SCHEMA,
            "active_version": self.active_version,
            "previous_version": self.previous_version,
            "protocol_compatible": self.protocol_compatible,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
        }


def plan_rollback(
    active_version: str,
    previous_version: str | None,
    *,
    previous_protocol_compatible: bool,
) -> DaemonRollbackPlan:
    """Permit rollback only to a distinct, protocol-compatible version."""

    if not active_version:
        raise ValueError("active_version is required")
    if previous_version is None:
        return DaemonRollbackPlan(
            active_version, None, False, False, "no_previous_version"
        )
    if not previous_protocol_compatible:
        return DaemonRollbackPlan(
            active_version,
            previous_version,
            False,
            False,
            "previous_protocol_incompatible",
        )
    return DaemonRollbackPlan(
        active_version, previous_version, True, True, "rollback_available"
    )


# Naming aliases make the contract easy to discover from the daemon vocabulary.
DaemonHotPathState = DaemonState
DaemonHotPathEvent = DaemonEvent
DaemonHotPathDecision = DaemonDecision


__all__ = [
    "DAEMON_HOT_PATH_SCHEMA",
    "DAEMON_PROTOCOL_VERSION",
    "CrashReceipt",
    "DaemonDecision",
    "DaemonEvent",
    "DaemonHealth",
    "DaemonHotPathController",
    "DaemonHotPathDecision",
    "DaemonHotPathEvent",
    "DaemonHotPathState",
    "DaemonPhase",
    "DaemonReconnectPolicy",
    "DaemonRollbackPlan",
    "DaemonStartup",
    "DaemonState",
    "classify_health",
    "guarded_call",
    "plan_rollback",
]
