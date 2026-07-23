"""Versioned AgentHost discovery and bounded advisory replay.

This module is intentionally product-neutral.  Consumers discover the agent
host through a small, versioned contract; the host does not import or name any
particular client application.  Operational advisories use a fixed catalog.
Workspace advisories additionally accept only allow-listed, client-supplied
metadata -- never model output, prompts, workspace contents, or secrets.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
import re
import secrets
from typing import Any, Final, Mapping

from agent.protocol_v1 import PROTOCOL_VERSION as AGENT_PROTOCOL_VERSION

HOST_PROTOCOL_SCHEMA: Final = "simplicio.agent-host/v1"
HOST_PROTOCOL_VERSION: Final = 1
ADVISORY_SCHEMA: Final = "simplicio.agent-advisory/v1"
WORKSPACE_OBSERVATION_SCHEMA: Final = "simplicio.workspace-observation/v1"
WORKSPACE_ADVISORY_SCHEMA: Final = "simplicio.workspace-advisory/v1"

# Keep this list limited to operations the daemon actually implements.  A
# client may safely fail closed when one of its required capabilities is absent.
HOST_CAPABILITIES: Final = (
    "host.advisories",
    "host.status",
    "invalidate",
    "ping",
    "shutdown",
    "turn.start",
    "turn.cancel",
    "turn.reconcile",
    "workspace.advisory",
    "workspace.observe",
)

_ADVISORY_CATALOG: Final[dict[str, tuple[str, str, str | None]]] = {
    "host.ready": ("info", "Agent host is ready.", None),
    "host.backpressure": ("warning", "Agent host is saturated.", "retry"),
    "host.draining": ("warning", "Agent host is draining.", None),
    "turn.completed": ("info", "Agent turn completed.", None),
    "turn.failed": ("warning", "Agent turn failed.", "inspect_logs"),
}

_WORKSPACE_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_HOST_INSTANCE_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")
_WORKSPACE_SNAPSHOT_FIELDS: Final = frozenset({
    "changed_files",
    "diagnostic_errors",
    "diagnostic_warnings",
    "test_status",
})
_WORKSPACE_TEST_STATUSES: Final = frozenset({
    "unknown",
    "not_run",
    "passing",
    "failing",
})
_WORKSPACE_COUNT_MAX: Final = 100_000
_WORKSPACE_ADVISORY_CATALOG: Final[dict[str, tuple[str, str, str, str | None]]] = {
    "workspace.changes_present": (
        "finding",
        "info",
        "Client metadata reports workspace changes.",
        None,
    ),
    "workspace.diagnostics_errors": (
        "risk",
        "warning",
        "Client metadata reports diagnostic errors.",
        "inspect_diagnostics",
    ),
    "workspace.diagnostics_warnings": (
        "risk",
        "warning",
        "Client metadata reports diagnostic warnings.",
        "inspect_diagnostics",
    ),
    "workspace.tests_failing": (
        "risk",
        "warning",
        "Client metadata reports a failing test state.",
        "inspect_tests",
    ),
    "workspace.tests_passing": (
        "finding",
        "info",
        "Client metadata reports a passing test state.",
        None,
    ),
    "workspace.verify_changes": (
        "suggestion",
        "info",
        "Verify the client-reported workspace changes.",
        "run_tests",
    ),
}


def new_host_instance_id() -> str:
    """Create an opaque, bounded identity for one daemon process lifetime.

    The value intentionally carries no host, user, workspace, or clock data.
    It is generated only by the daemon at process start and is never persisted.
    """
    return secrets.token_urlsafe(24)


def _host_instance_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _HOST_INSTANCE_ID_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("host_instance_id must be an opaque 16-64 character identifier")
    return value


def require_current_host_instance(
    expected: Any,
    *,
    current: str,
) -> None:
    """Reject a request tied to another daemon process, without echoing it."""
    if _host_instance_id(expected) != current:
        raise ValueError("host_instance_id does not match the active host incarnation")


def host_protocol_metadata(
    profile: str,
    *,
    host_instance_id: str | None = None,
) -> dict[str, Any]:
    """Return the stable discovery envelope included in every host response."""
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("profile must be a non-empty string")
    metadata = {
        "protocol_schema": HOST_PROTOCOL_SCHEMA,
        "protocol_version": HOST_PROTOCOL_VERSION,
        "agent_protocol": AGENT_PROTOCOL_VERSION,
        "profile": profile,
        "capabilities": list(HOST_CAPABILITIES),
        "advisory_schema": ADVISORY_SCHEMA,
        "workspace_observation_schema": WORKSPACE_OBSERVATION_SCHEMA,
        "workspace_advisory_schema": WORKSPACE_ADVISORY_SCHEMA,
    }
    # Omission preserves the v1 discovery shape for direct in-process callers.
    # The daemon always supplies this additive v1 field during rollout.
    if host_instance_id is not None:
        metadata["host_instance_id"] = _host_instance_id(host_instance_id)
    return metadata


class HostAdvisoryBuffer:
    """Thread-safe, bounded replay buffer for generic host attention signals."""

    def __init__(
        self,
        *,
        max_events: int = 128,
        host_instance_id: str | None = None,
    ) -> None:
        if (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or max_events < 1
        ):
            raise ValueError("max_events must be a positive integer")
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._sequence = 0
        self._lock = threading.Lock()
        self._host_instance_id = (
            _host_instance_id(host_instance_id)
            if host_instance_id is not None
            else None
        )

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
            replay = {
                "schema": ADVISORY_SCHEMA,
                "events": events,
                "next_cursor": self._sequence,
                "truncated": truncated,
            }
            if self._host_instance_id is not None:
                replay["host_instance_id"] = self._host_instance_id
            return replay


@dataclass(slots=True)
class _WorkspaceStream:
    max_events: int
    revision: int = 0
    sequence: int = 0
    events: deque[dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.events = deque(maxlen=self.max_events)


def _positive_limit(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _workspace_id(value: Any) -> str:
    if not isinstance(value, str) or _WORKSPACE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("workspace_id must be an opaque 1-64 character identifier")
    return value


def _workspace_cursor(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("after must be a non-negative integer")
    return value


def _workspace_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("revision must be a positive integer")
    return value


def _workspace_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be an object")
    fields = set(snapshot)
    if fields != _WORKSPACE_SNAPSHOT_FIELDS:
        raise ValueError("snapshot fields must match the metadata-only allowlist")

    normalized: dict[str, Any] = {}
    for name in ("changed_files", "diagnostic_errors", "diagnostic_warnings"):
        value = snapshot[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= _WORKSPACE_COUNT_MAX
        ):
            raise ValueError(
                f"{name} must be an integer between 0 and {_WORKSPACE_COUNT_MAX}"
            )
        normalized[name] = value

    test_status = snapshot["test_status"]
    if not isinstance(test_status, str) or test_status not in _WORKSPACE_TEST_STATUSES:
        raise ValueError("test_status must be unknown, not_run, passing, or failing")
    normalized["test_status"] = test_status
    return normalized


def _derive_workspace_advisories(
    snapshot: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    derived: list[tuple[str, dict[str, Any]]] = []
    changed_files = snapshot["changed_files"]
    diagnostic_errors = snapshot["diagnostic_errors"]
    diagnostic_warnings = snapshot["diagnostic_warnings"]
    test_status = snapshot["test_status"]

    if changed_files:
        derived.append(("workspace.changes_present", {"changed_files": changed_files}))
    if diagnostic_errors:
        derived.append((
            "workspace.diagnostics_errors",
            {"diagnostic_errors": diagnostic_errors},
        ))
    if diagnostic_warnings:
        derived.append((
            "workspace.diagnostics_warnings",
            {"diagnostic_warnings": diagnostic_warnings},
        ))
    if test_status == "failing":
        derived.append(("workspace.tests_failing", {"test_status": test_status}))
    elif test_status == "passing":
        derived.append(("workspace.tests_passing", {"test_status": test_status}))
    if changed_files and test_status in {"unknown", "not_run"}:
        derived.append(("workspace.verify_changes", {"test_status": test_status}))
    return derived


def _copy_workspace_event(event: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(event)
    copied["facts"] = dict(event["facts"])
    return copied


class WorkspaceAdvisoryStore:
    """Bounded, per-workspace deterministic advisory streams.

    The store accepts only a fixed metadata snapshot supplied by the caller.
    It never reads a workspace and has no execution, Runtime, tool, or model
    dependency.  Original snapshots are not retained; only redacted events
    from the fixed catalog remain in the bounded replay buffers.
    """

    def __init__(
        self,
        *,
        max_workspaces: int = 32,
        max_events_per_workspace: int = 64,
        host_instance_id: str | None = None,
    ) -> None:
        self._max_workspaces = _positive_limit(max_workspaces, name="max_workspaces")
        self._max_events_per_workspace = _positive_limit(
            max_events_per_workspace, name="max_events_per_workspace"
        )
        self._streams: dict[str, _WorkspaceStream] = {}
        self._lock = threading.Lock()
        self._host_instance_id = (
            _host_instance_id(host_instance_id)
            if host_instance_id is not None
            else None
        )

    def observe(
        self,
        *,
        workspace_id: str,
        revision: int,
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Accept one strictly ordered metadata snapshot and publish signals."""
        workspace_id = _workspace_id(workspace_id)
        revision = _workspace_revision(revision)
        snapshot = _workspace_snapshot(snapshot)
        derived = _derive_workspace_advisories(snapshot)

        with self._lock:
            stream = self._streams.get(workspace_id)
            if stream is None:
                if revision != 1:
                    raise ValueError("revision must equal 1")
                if len(self._streams) >= self._max_workspaces:
                    raise ValueError("workspace advisory capacity is full")
                stream = _WorkspaceStream(self._max_events_per_workspace)
                self._streams[workspace_id] = stream
            else:
                expected_revision = stream.revision + 1
                if revision != expected_revision:
                    raise ValueError(f"revision must equal {expected_revision}")

            for code, facts in derived:
                kind, severity, summary, suggested_action = _WORKSPACE_ADVISORY_CATALOG[
                    code
                ]
                stream.sequence += 1
                stream.events.append({
                    "schema": WORKSPACE_ADVISORY_SCHEMA,
                    "workspace_id": workspace_id,
                    "sequence": stream.sequence,
                    "observation_revision": revision,
                    "kind": kind,
                    "code": code,
                    "severity": severity,
                    "summary": summary,
                    "suggested_action": suggested_action,
                    "facts": dict(facts),
                    "redaction": "metadata_only",
                    "effect": "none",
                    "ts_wall_ns": time.time_ns(),
                })
            stream.revision = revision
            observation = {
                "schema": WORKSPACE_OBSERVATION_SCHEMA,
                "workspace_id": workspace_id,
                "accepted_revision": revision,
                "published_count": len(derived),
                "next_cursor": stream.sequence,
                "effect": "none",
            }
            if self._host_instance_id is not None:
                observation["host_instance_id"] = self._host_instance_id
            return observation

    def replay(self, *, workspace_id: str, after: int = 0) -> dict[str, Any]:
        """Replay one workspace stream strictly after a validated cursor."""
        workspace_id = _workspace_id(workspace_id)
        after = _workspace_cursor(after)
        with self._lock:
            stream = self._streams.get(workspace_id)
            if stream is None:
                if after:
                    raise ValueError(
                        "after exceeds the current workspace advisory sequence"
                    )
                replay = {
                    "schema": WORKSPACE_ADVISORY_SCHEMA,
                    "workspace_id": workspace_id,
                    "events": [],
                    "next_cursor": 0,
                    "truncated": False,
                }
                if self._host_instance_id is not None:
                    replay["host_instance_id"] = self._host_instance_id
                return replay
            if after > stream.sequence:
                raise ValueError(
                    "after exceeds the current workspace advisory sequence"
                )
            retained = list(stream.events)
            first_sequence = (
                retained[0]["sequence"] if retained else stream.sequence + 1
            )
            truncated = bool(retained) and after < first_sequence - 1
            events = [
                _copy_workspace_event(event)
                for event in retained
                if event["sequence"] > after
            ]
            replay = {
                "schema": WORKSPACE_ADVISORY_SCHEMA,
                "workspace_id": workspace_id,
                "events": events,
                "next_cursor": stream.sequence,
                "truncated": truncated,
            }
            if self._host_instance_id is not None:
                replay["host_instance_id"] = self._host_instance_id
            return replay
