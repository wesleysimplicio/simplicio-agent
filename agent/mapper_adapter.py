"""Read-only consumer boundary for the Mapper ContextSnapshot/ContextGraph v1.

The Mapper owns the schemas and their validation.  This module only imports the
public installed validator or consumes the public CLI JSON transport; it does
not copy a schema, generate a competing payload, or read source files as a
fallback.  Graph expansion is deliberately handle-scoped and budgeted.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.resources
import json
import posixpath
import re
import subprocess
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Generic, Protocol, TypeVar

CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
CONTEXT_GRAPH_SCHEMA = "simplicio.context-graph/v1"
MAPPER_PRODUCER = "simplicio-mapper"
MIN_MAPPER_VERSION = "0.24.1"
MAX_CACHE_BYTES = 16 * 1024 * 1024

T = TypeVar("T")
Validator = Callable[..., Mapping[str, Any]]


class AdapterStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    INCOMPATIBLE_SCHEMA = "incompatible_schema"
    STALE = "stale"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FIDELITY_REJECTED = "fidelity_rejected"
    TAMPERED = "tampered"


@dataclass(frozen=True)
class CausalScope:
    """The identity under which a snapshot revision is pinned."""

    session_id: str
    turn_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("session_id", self.session_id),
            ("turn_id", self.turn_id),
            ("attempt_id", self.attempt_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.session_id, self.turn_id, self.attempt_id


@dataclass(frozen=True)
class SnapshotRequest:
    root: Path
    repository_id: str
    profile: str
    revision: str
    causal_scope: CausalScope
    build_config_hash: str = ""
    source_set: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    task_query: str = ""
    selection_policy: str = "deterministic"
    budget_tokens: int = 0
    require_complete: bool = False
    max_age_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("root must be pathlib.Path")
        for name, value in (
            ("repository_id", self.repository_id),
            ("profile", self.profile),
            ("revision", self.revision),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.budget_tokens < 0:
            raise ValueError("budget_tokens must be >= 0")
        if self.max_age_seconds is not None and self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive when provided")


@dataclass(frozen=True)
class ContextSnapshotHandle:
    schema: str
    schema_version: str
    producer: str
    producer_version: str
    repository_id: str
    snapshot_id: str
    revision: str
    root_hash: str
    fidelity: Mapping[str, Any]
    config_hash: str
    generated_at: str
    causal_scope: CausalScope

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], causal_scope: CausalScope
    ) -> "ContextSnapshotHandle":
        producer = payload.get("producer")
        if not isinstance(producer, Mapping):
            raise ValueError("producer metadata is missing")
        values = {
            "schema": payload.get("schema"),
            "schema_version": payload.get("schema_version"),
            "producer": producer.get("name"),
            "producer_version": producer.get("version"),
            "repository_id": payload.get("repository_id"),
            "snapshot_id": payload.get("snapshot_id"),
            "revision": payload.get("revision"),
            "root_hash": payload.get("root_hash"),
            "fidelity": payload.get("fidelity"),
            "config_hash": payload.get("build_config_hash", ""),
            "generated_at": payload.get("generated_at"),
        }
        if not isinstance(values["fidelity"], Mapping):
            raise ValueError("fidelity metadata is missing")
        for name, value in values.items():
            if name == "fidelity":
                continue
            if not isinstance(value, str) or (name != "config_hash" and not value):
                raise ValueError(f"{name} is missing")
        if values["producer"] != MAPPER_PRODUCER:
            raise ValueError("unexpected producer")
        return cls(causal_scope=causal_scope, **values)


@dataclass(frozen=True)
class MapperCapabilities:
    transport: str
    producer: str
    producer_version: str
    schema_ids: tuple[str, ...]
    contract_manifest_digest: str
    available: bool = True
    reason: str = ""

    @property
    def supports_v1(self) -> bool:
        return (
            self.available
            and _version_at_least(self.producer_version, MIN_MAPPER_VERSION)
            and CONTEXT_SNAPSHOT_SCHEMA in self.schema_ids
            and CONTEXT_GRAPH_SCHEMA in self.schema_ids
        )


@dataclass(frozen=True)
class ResultMetrics:
    latency_ms: float = 0.0
    payload_bytes: int = 0
    cache_hit: bool = False
    materialized_nodes: int = 0
    materialized_edges: int = 0
    fallback_reason: str | None = None


@dataclass(frozen=True)
class MapperResult(Generic[T]):
    status: AdapterStatus
    value: T | None = None
    reason_code: str = ""
    reason: str = ""
    metrics: ResultMetrics = field(default_factory=ResultMetrics)

    @classmethod
    def success(
        cls, value: T, *, metrics: ResultMetrics | None = None
    ) -> "MapperResult[T]":
        return cls(
            AdapterStatus.AVAILABLE, value=value, metrics=metrics or ResultMetrics()
        )

    @classmethod
    def failure(
        cls,
        status: AdapterStatus,
        reason_code: str,
        reason: str,
        *,
        metrics: ResultMetrics | None = None,
    ) -> "MapperResult[T]":
        return cls(
            status,
            reason_code=reason_code,
            reason=reason,
            metrics=metrics or ResultMetrics(),
        )


@dataclass(frozen=True)
class ExpandedContext:
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class CachePolicy:
    max_entries: int = 64
    max_bytes: int = MAX_CACHE_BYTES
    ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_entries < 1 or self.max_bytes < 1 or self.ttl_seconds <= 0:
            raise ValueError("cache bounds must be positive")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int
    hits: int
    misses: int
    evictions: int


@dataclass
class _CacheEntry:
    payload: Mapping[str, Any]
    handle: ContextSnapshotHandle
    size: int
    expires_at: float


class SnapshotTransport(Protocol):
    def capabilities(self) -> MapperCapabilities: ...

    def create_or_resolve_snapshot(
        self, request: SnapshotRequest
    ) -> MapperResult[Mapping[str, Any]]: ...

    def refresh(self, request: SnapshotRequest) -> MapperResult[Mapping[str, Any]]: ...


class _SnapshotCache:
    def __init__(
        self, policy: CachePolicy, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str, str, str, str, str], _CacheEntry] = (
            OrderedDict()
        )
        self._latest: dict[
            tuple[str, str, str, str, str], tuple[str, str, str, str, str, str]
        ] = {}
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._lock = RLock()

    @staticmethod
    def _scope(
        request: SnapshotRequest, producer_version: str
    ) -> tuple[str, str, str, str, str]:
        return (
            request.repository_id,
            request.profile,
            request.revision,
            request.build_config_hash,
            producer_version,
        )

    @staticmethod
    def _key(
        scope: tuple[str, str, str, str, str], snapshot_id: str
    ) -> tuple[str, str, str, str, str, str]:
        return (*scope, snapshot_id)

    def get(
        self, request: SnapshotRequest, producer_version: str
    ) -> _CacheEntry | None:
        with self._lock:
            scope = self._scope(request, producer_version)
            key = self._latest.get(scope)
            entry = self._entries.get(key) if key else None
            if entry is None or entry.expires_at <= self._clock():
                if key is not None:
                    self._remove(key)
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry

    def put(
        self,
        request: SnapshotRequest,
        handle: ContextSnapshotHandle,
        payload: Mapping[str, Any],
    ) -> None:
        encoded = _canonical_json(payload)
        if len(encoded) > self.policy.max_bytes:
            return
        with self._lock:
            scope = self._scope(request, handle.producer_version)
            key = self._key(scope, handle.snapshot_id)
            if key in self._entries:
                self._remove(key)
            self._entries[key] = _CacheEntry(
                payload, handle, len(encoded), self._clock() + self.policy.ttl_seconds
            )
            self._latest[scope] = key
            self._bytes += len(encoded)
            self._trim()

    def _remove(self, key: tuple[str, str, str, str, str, str]) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        self._bytes -= entry.size
        scope = key[:-1]
        if self._latest.get(scope) == key:
            self._latest.pop(scope, None)

    def _trim(self) -> None:
        while (
            len(self._entries) > self.policy.max_entries
            or self._bytes > self.policy.max_bytes
        ):
            key = next(iter(self._entries))
            self._remove(key)
            self._evictions += 1

    def find_handle(self, handle: ContextSnapshotHandle) -> _CacheEntry | None:
        with self._lock:
            for key, entry in self._entries.items():
                if key[-1] == handle.snapshot_id and entry.handle == handle:
                    return entry
        return None

    def invalidate(
        self, *, repository_id: str | None = None, revision: str | None = None
    ) -> None:
        with self._lock:
            for key in list(self._entries):
                if repository_id is not None and key[0] != repository_id:
                    continue
                if revision is not None and key[2] != revision:
                    continue
                self._remove(key)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                len(self._entries),
                self._bytes,
                self._hits,
                self._misses,
                self._evictions,
            )


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _reason_codes(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = report.get("reason_codes", [])
    return (
        [value for value in values if isinstance(value, Mapping)]
        if isinstance(values, list)
        else []
    )


def _status_for_reason(code: str) -> AdapterStatus:
    if code in {
        "SNAPSHOT_HASH_MISMATCH",
        "GRAPH_HASH_MISMATCH",
        "ROOT_HASH_MISMATCH",
        "FRESHNESS_ROOT_HASH_MISMATCH",
    }:
        return AdapterStatus.TAMPERED
    if code.startswith("UNSUPPORTED_") or code in {
        "SNAPSHOT_SCHEMA_INVALID",
        "GRAPH_SCHEMA_INVALID",
    }:
        return AdapterStatus.INCOMPATIBLE_SCHEMA
    if code in {
        "PAYLOAD_TOO_LARGE",
        "PAYLOAD_TOO_DEEP",
        "SOURCE_HANDLE_TRAVERSAL",
        "SOURCE_HANDLE_INVALID",
    }:
        return AdapterStatus.INCOMPATIBLE_SCHEMA
    return AdapterStatus.INCOMPATIBLE_SCHEMA


def _default_validator() -> Validator:
    module = importlib.import_module("simplicio_mapper.context_contract")
    return module.validate_context_payload


class MapperClient:
    """Typed, read-only Agent boundary around one explicit Mapper transport."""

    def __init__(
        self,
        transport: SnapshotTransport,
        *,
        validator: Validator | None = None,
        cache_policy: CachePolicy | None = None,
        expected_contract_manifest_digest: str | None = None,
        event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.transport = transport
        self.validator = validator
        self._cache = _SnapshotCache(cache_policy or CachePolicy())
        self._expected_contract_manifest_digest = expected_contract_manifest_digest
        self._event_sink = event_sink
        self._pins: dict[tuple[str, str, str], ContextSnapshotHandle] = {}
        self._pin_lock = RLock()

    def capabilities(self) -> MapperCapabilities:
        return self.transport.capabilities()

    def create_or_resolve_snapshot(
        self, request: SnapshotRequest
    ) -> MapperResult[ContextSnapshotHandle]:
        started = time.monotonic()
        capabilities = self.capabilities()
        if not capabilities.available:
            return self._finish(
                "create_or_resolve_snapshot",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.UNAVAILABLE,
                    "MAPPER_UNAVAILABLE",
                    capabilities.reason or "Mapper transport is unavailable",
                ),
            )
        if (
            self._expected_contract_manifest_digest
            and capabilities.contract_manifest_digest
            != self._expected_contract_manifest_digest
        ):
            return self._finish(
                "create_or_resolve_snapshot",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.INCOMPATIBLE_SCHEMA,
                    "CONTRACT_MANIFEST_DIGEST_MISMATCH",
                    "Mapper contract manifest digest is not the pinned digest",
                ),
            )
        if not capabilities.supports_v1:
            return self._finish(
                "create_or_resolve_snapshot",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.INCOMPATIBLE_SCHEMA,
                    "CAPABILITY_MISSING_CONTEXT_V1",
                    capabilities.reason
                    or "Mapper does not advertise ContextSnapshot/ContextGraph v1",
                ),
            )
        cached = self._cache.get(request, capabilities.producer_version)
        if cached is not None:
            pin_result = self._pin(cached.handle)
            if pin_result is not None:
                return self._finish(
                    "create_or_resolve_snapshot", request.causal_scope, pin_result
                )
            return self._finish(
                "create_or_resolve_snapshot",
                request.causal_scope,
                MapperResult.success(
                    cached.handle,
                    metrics=ResultMetrics(
                        latency_ms=(time.monotonic() - started) * 1000,
                        payload_bytes=cached.size,
                        cache_hit=True,
                    ),
                ),
            )
        result = self.transport.create_or_resolve_snapshot(request)
        accepted = self._accept_transport_result(
            result,
            request,
            started,
            expected_producer_version=capabilities.producer_version,
        )
        return self._finish(
            "create_or_resolve_snapshot", request.causal_scope, accepted
        )

    def refresh(self, request: SnapshotRequest) -> MapperResult[ContextSnapshotHandle]:
        started = time.monotonic()
        capabilities = self.capabilities()
        if not capabilities.available:
            return self._finish(
                "refresh",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.UNAVAILABLE,
                    "MAPPER_UNAVAILABLE",
                    capabilities.reason or "Mapper transport is unavailable",
                ),
            )
        if (
            self._expected_contract_manifest_digest
            and capabilities.contract_manifest_digest
            != self._expected_contract_manifest_digest
        ):
            return self._finish(
                "refresh",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.INCOMPATIBLE_SCHEMA,
                    "CONTRACT_MANIFEST_DIGEST_MISMATCH",
                    "Mapper contract manifest digest is not the pinned digest",
                ),
            )
        if not capabilities.supports_v1:
            return self._finish(
                "refresh",
                request.causal_scope,
                MapperResult.failure(
                    AdapterStatus.INCOMPATIBLE_SCHEMA,
                    "CAPABILITY_MISSING_CONTEXT_V1",
                    capabilities.reason
                    or "Mapper does not advertise ContextSnapshot/ContextGraph v1",
                ),
            )
        result = self.transport.refresh(request)
        accepted = self._accept_transport_result(
            result,
            request,
            started,
            refresh=True,
            expected_producer_version=capabilities.producer_version,
        )
        return self._finish("refresh", request.causal_scope, accepted)

    def revalidate(
        self, request: SnapshotRequest
    ) -> MapperResult[ContextSnapshotHandle]:
        """Refresh and validate the pinned causal scope without changing it silently."""
        return self.refresh(request)

    def get_snapshot_metadata(
        self, scope: CausalScope
    ) -> MapperResult[ContextSnapshotHandle]:
        with self._pin_lock:
            handle = self._pins.get(scope.key)
        if handle is None:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "SNAPSHOT_NOT_PINNED",
                "no snapshot is pinned for scope",
            )
        return MapperResult.success(handle)

    def resolve_node(
        self, handle: ContextSnapshotHandle, node_id: str
    ) -> MapperResult[Mapping[str, Any]]:
        entry = self._cache.find_handle(handle)
        if entry is None:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "SNAPSHOT_NOT_CACHED",
                "snapshot payload is not materialized",
            )
        for node in _graph_rows(entry.payload, "nodes"):
            if node.get("id") == node_id:
                return MapperResult.success(node)
        return MapperResult.failure(
            AdapterStatus.UNAVAILABLE, "NODE_HANDLE_NOT_FOUND", "node handle is absent"
        )

    def resolve_edge(
        self, handle: ContextSnapshotHandle, edge_id: str
    ) -> MapperResult[Mapping[str, Any]]:
        entry = self._cache.find_handle(handle)
        if entry is None:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "SNAPSHOT_NOT_CACHED",
                "snapshot payload is not materialized",
            )
        for edge in _graph_rows(entry.payload, "edges"):
            if edge.get("id") == edge_id:
                return MapperResult.success(edge)
        return MapperResult.failure(
            AdapterStatus.UNAVAILABLE, "EDGE_HANDLE_NOT_FOUND", "edge handle is absent"
        )

    def resolve_source_handle(
        self, handle: ContextSnapshotHandle, source: Mapping[str, Any]
    ) -> MapperResult[Mapping[str, Any]]:
        if not _valid_source_handle(source):
            return MapperResult.failure(
                AdapterStatus.INCOMPATIBLE_SCHEMA,
                "SOURCE_HANDLE_INVALID",
                "source handle is not a safe reversible handle",
            )
        entry = self._cache.find_handle(handle)
        if entry is None:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "SNAPSHOT_NOT_CACHED",
                "snapshot payload is not materialized",
            )
        wanted = _canonical_json(source)
        for row in (
            *_graph_rows(entry.payload, "nodes"),
            *_graph_rows(entry.payload, "edges"),
        ):
            candidate = row.get("source") or row.get("source_handle")
            if isinstance(candidate, Mapping) and _canonical_json(candidate) == wanted:
                return MapperResult.success(candidate)
        return MapperResult.failure(
            AdapterStatus.UNAVAILABLE,
            "SOURCE_HANDLE_NOT_FOUND",
            "source handle is absent",
        )

    def expand_context(
        self,
        handle: ContextSnapshotHandle,
        *,
        handles: Sequence[str] = (),
        scales: Sequence[str] = (),
        budget_nodes: int = 100,
        budget_edges: int = 200,
    ) -> MapperResult[ExpandedContext]:
        entry = self._cache.find_handle(handle)
        if entry is None:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "SNAPSHOT_NOT_CACHED",
                "snapshot payload is not materialized",
            )
        if budget_nodes < 0 or budget_edges < 0:
            return MapperResult.failure(
                AdapterStatus.INSUFFICIENT_CONTEXT,
                "INVALID_EXPANSION_BUDGET",
                "budgets must be non-negative",
            )
        wanted = set(handles)
        allowed_scales = set(scales)
        nodes = tuple(
            node
            for node in _graph_rows(entry.payload, "nodes")
            if (not wanted or node.get("id") in wanted)
            and (not allowed_scales or node.get("scale") in allowed_scales)
        )
        if len(nodes) > budget_nodes:
            return MapperResult.failure(
                AdapterStatus.INSUFFICIENT_CONTEXT,
                "EXPANSION_BUDGET_EXCEEDED",
                "node expansion exceeds the declared budget",
                metrics=ResultMetrics(fallback_reason="budget_exceeded"),
            )
        node_ids = {node.get("id") for node in nodes}
        edges = tuple(
            edge
            for edge in _graph_rows(entry.payload, "edges")
            if (
                not wanted
                or edge.get("id") in wanted
                or edge.get("source") in node_ids
                or edge.get("target") in node_ids
            )
        )
        if len(edges) > budget_edges:
            return MapperResult.failure(
                AdapterStatus.INSUFFICIENT_CONTEXT,
                "EXPANSION_BUDGET_EXCEEDED",
                "edge expansion exceeds the declared budget",
                metrics=ResultMetrics(fallback_reason="budget_exceeded"),
            )
        return MapperResult.success(
            ExpandedContext(nodes, edges),
            metrics=ResultMetrics(
                materialized_nodes=len(nodes), materialized_edges=len(edges)
            ),
        )

    def invalidate(
        self, *, repository_id: str | None = None, revision: str | None = None
    ) -> None:
        self._cache.invalidate(repository_id=repository_id, revision=revision)

    def cache_stats(self) -> CacheStats:
        return self._cache.stats()

    def _accept_transport_result(
        self,
        result: MapperResult[Mapping[str, Any]],
        request: SnapshotRequest,
        started: float,
        *,
        refresh: bool = False,
        expected_producer_version: str = "",
    ) -> MapperResult[ContextSnapshotHandle]:
        if result.status is not AdapterStatus.AVAILABLE or result.value is None:
            return MapperResult.failure(
                result.status,
                result.reason_code or "MAPPER_TRANSPORT_FAILED",
                result.reason or "Mapper transport failed",
                metrics=replace_metrics(
                    result.metrics, latency_ms=(time.monotonic() - started) * 1000
                ),
            )
        payload = result.value
        try:
            validator = self.validator or _default_validator()
            report = validator(payload, source_root=str(request.root))
        except (ImportError, ModuleNotFoundError) as exc:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE, "MAPPER_UNAVAILABLE", str(exc)
            )
        except Exception as exc:  # validator boundary must remain typed
            return MapperResult.failure(
                AdapterStatus.INCOMPATIBLE_SCHEMA, "VALIDATOR_ERROR", str(exc)
            )
        if not report.get("valid"):
            reasons = _reason_codes(report)
            first = reasons[0] if reasons else {}
            code = str(first.get("code") or "CONTRACT_REJECTED")
            message = str(
                first.get("message") or "Mapper contract rejected the payload"
            )
            return MapperResult.failure(_status_for_reason(code), code, message)
        try:
            handle = ContextSnapshotHandle.from_payload(payload, request.causal_scope)
        except (TypeError, ValueError) as exc:
            return MapperResult.failure(
                AdapterStatus.INCOMPATIBLE_SCHEMA, "HANDLE_METADATA_INVALID", str(exc)
            )
        if (
            handle.repository_id != request.repository_id
            or handle.revision != request.revision
        ):
            return MapperResult.failure(
                AdapterStatus.STALE,
                "STALE_REVISION",
                "snapshot identity does not match the request",
            )
        if (
            expected_producer_version
            and handle.producer_version != expected_producer_version
        ):
            return MapperResult.failure(
                AdapterStatus.INCOMPATIBLE_SCHEMA,
                "PRODUCER_VERSION_MISMATCH",
                "snapshot producer version differs from negotiated capability",
            )
        if request.max_age_seconds is not None and _is_expired(
            handle.generated_at, request.max_age_seconds
        ):
            return MapperResult.failure(
                AdapterStatus.STALE,
                "SNAPSHOT_EXPIRED",
                "snapshot freshness budget has elapsed",
            )
        omissions = handle.fidelity.get("omissions", [])
        if payload.get("needs_broader_context") or omissions:
            status = (
                AdapterStatus.FIDELITY_REJECTED
                if request.require_complete
                else AdapterStatus.INSUFFICIENT_CONTEXT
            )
            return MapperResult.failure(
                status,
                "FIDELITY_INSUFFICIENT",
                "Mapper snapshot declares broader context is required",
            )
        pin_result = self._pin(handle)
        if pin_result is not None:
            return pin_result
        self._cache.put(request, handle, payload)
        return MapperResult.success(
            handle,
            metrics=ResultMetrics(
                latency_ms=(time.monotonic() - started) * 1000,
                payload_bytes=len(_canonical_json(payload)),
                cache_hit=False,
                fallback_reason="refresh" if refresh else None,
            ),
        )

    def _finish(
        self,
        operation: str,
        scope: CausalScope,
        result: MapperResult[Any],
    ) -> MapperResult[Any]:
        if self._event_sink is not None:
            event = {
                "schema": "simplicio.mapper-adapter-event/v1",
                "operation": operation,
                "status": result.status.value,
                "reason_code": result.reason_code,
                "session_id": scope.session_id,
                "turn_id": scope.turn_id,
                "attempt_id": scope.attempt_id,
                "latency_ms": result.metrics.latency_ms,
                "payload_bytes": result.metrics.payload_bytes,
                "cache_hit": result.metrics.cache_hit,
                "materialized_nodes": result.metrics.materialized_nodes,
                "materialized_edges": result.metrics.materialized_edges,
                "fallback_reason": result.metrics.fallback_reason,
            }
            try:
                self._event_sink(event)
            except Exception:
                # Observability must never change the read-only adapter result.
                pass
        return result

    def _pin(
        self, handle: ContextSnapshotHandle
    ) -> MapperResult[ContextSnapshotHandle] | None:
        with self._pin_lock:
            existing = self._pins.get(handle.causal_scope.key)
            if existing is not None and (
                existing.revision != handle.revision
                or existing.snapshot_id != handle.snapshot_id
            ):
                return MapperResult.failure(
                    AdapterStatus.STALE,
                    "PIN_REVISION_CHANGED",
                    "a causal attempt cannot switch snapshot revision or identity",
                )
            self._pins[handle.causal_scope.key] = handle
        return None


def replace_metrics(metrics: ResultMetrics, **changes: Any) -> ResultMetrics:
    values = {
        "latency_ms": metrics.latency_ms,
        "payload_bytes": metrics.payload_bytes,
        "cache_hit": metrics.cache_hit,
        "materialized_nodes": metrics.materialized_nodes,
        "materialized_edges": metrics.materialized_edges,
        "fallback_reason": metrics.fallback_reason,
    }
    values.update(changes)
    return ResultMetrics(**values)


def _graph_rows(
    payload: Mapping[str, Any], field_name: str
) -> tuple[Mapping[str, Any], ...]:
    graph = payload.get("graph")
    if not isinstance(graph, Mapping):
        return ()
    rows = graph.get(field_name)
    return (
        tuple(row for row in rows if isinstance(row, Mapping))
        if isinstance(rows, list)
        else ()
    )


def _valid_source_handle(source: Mapping[str, Any]) -> bool:
    if not isinstance(source, Mapping) or set(source).difference({"file", "line", "span"}):
        return False
    file_name = source.get("file")
    if not isinstance(file_name, str) or not file_name or "\x00" in file_name or "\\" in file_name:
        return False
    if file_name != "<unknown>" and not file_name.startswith(("module:", "layer:", "adr:")):
        if (
            file_name.startswith("/")
            or re.match(r"^[A-Za-z]:/", file_name)
            or posixpath.normpath(file_name) != file_name
            or file_name == ".."
            or file_name.startswith("../")
        ):
            return False
    line = source.get("line")
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
        return False
    span = source.get("span")
    return not (
        span is not None
        and (
            not isinstance(span, list)
            or len(span) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in span)
            or span[0] > span[1]
        )
    )


def _version_at_least(actual: str, minimum: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        numbers: list[int] = []
        for piece in value.split("."):
            digits = "".join(character for character in piece if character.isdigit())
            if not digits:
                break
            numbers.append(int(digits))
        return tuple(numbers or [0])

    return parts(actual) >= parts(minimum)


def _is_expired(generated_at: str, max_age_seconds: float) -> bool:
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return time.time() - parsed.timestamp() > max_age_seconds


class InstalledMapperBindingTransport:
    """Use only public APIs from an installed ``simplicio-mapper`` package."""

    def __init__(self) -> None:
        self._error: str | None = None
        try:
            self._mapper = importlib.import_module("simplicio_mapper")
            self._snapshot = importlib.import_module(
                "simplicio_mapper.context_snapshot"
            )
            self._version = str(getattr(self._mapper, "__version__", ""))
            self._manifest_digest = self._read_manifest_digest()
        except (ImportError, ModuleNotFoundError, OSError) as exc:
            self._error = str(exc)
            self._mapper = self._snapshot = None
            self._version = ""
            self._manifest_digest = ""

    def capabilities(self) -> MapperCapabilities:
        if self._error:
            return MapperCapabilities(
                "binding",
                MAPPER_PRODUCER,
                "",
                (),
                "",
                available=False,
                reason=self._error,
            )
        return MapperCapabilities(
            "binding",
            MAPPER_PRODUCER,
            self._version,
            (CONTEXT_SNAPSHOT_SCHEMA, CONTEXT_GRAPH_SCHEMA),
            self._manifest_digest,
        )

    def create_or_resolve_snapshot(
        self, request: SnapshotRequest
    ) -> MapperResult[Mapping[str, Any]]:
        if self._error:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE, "MAPPER_UNAVAILABLE", self._error
            )
        try:
            payload = self._snapshot.build_context_snapshot(
                str(request.root),
                revision=request.revision,
                build_config_hash=request.build_config_hash,
                source_set=request.source_set or None,
                exclusions=request.exclusions or None,
                task_query=request.task_query,
                selection_policy=request.selection_policy,
                budget_tokens=request.budget_tokens,
            )
        except TimeoutError as exc:
            return MapperResult.failure(
                AdapterStatus.TIMEOUT, "MAPPER_TIMEOUT", str(exc)
            )
        except Exception as exc:  # external adapter boundary
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE, "MAPPER_EXECUTION_ERROR", str(exc)
            )
        return MapperResult.success(payload)

    def refresh(self, request: SnapshotRequest) -> MapperResult[Mapping[str, Any]]:
        return self.create_or_resolve_snapshot(request)

    def _read_manifest_digest(self) -> str:
        resource = importlib.resources.files("simplicio_mapper").joinpath(
            "contracts/context-snapshot/v1/contract-manifest.json"
        )
        return "sha256:" + hashlib.sha256(resource.read_bytes()).hexdigest()


class MapperCliJsonTransport:
    """Consume the Mapper's public ``snapshot build --json`` CLI contract."""

    def __init__(
        self,
        command: Sequence[str] = ("simplicio-mapper",),
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self._capabilities: MapperCapabilities | None = None

    def capabilities(self) -> MapperCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        try:
            completed = subprocess.run(
                [*self.command, "version", "--json"],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._capabilities = MapperCapabilities(
                "cli-json",
                MAPPER_PRODUCER,
                "",
                (),
                "",
                available=False,
                reason=str(exc),
            )
            return self._capabilities
        if completed.returncode != 0:
            self._capabilities = MapperCapabilities(
                "cli-json",
                MAPPER_PRODUCER,
                "",
                (),
                "",
                available=False,
                reason="version probe failed",
            )
            return self._capabilities
        version = _version_from_output(completed.stdout)
        self._capabilities = MapperCapabilities(
            "cli-json",
            MAPPER_PRODUCER,
            version,
            (CONTEXT_SNAPSHOT_SCHEMA, CONTEXT_GRAPH_SCHEMA) if version else (),
            "",
            available=bool(version),
            reason="" if version else "version response was not structured JSON",
        )
        return self._capabilities

    def create_or_resolve_snapshot(
        self, request: SnapshotRequest
    ) -> MapperResult[Mapping[str, Any]]:
        argv = [
            *self.command,
            "snapshot",
            "build",
            "--root",
            str(request.root),
            "--out",
            ".simplicio",
            "--json",
        ]
        if request.build_config_hash:
            argv.extend(("--build-config-hash", request.build_config_hash))
        if request.task_query:
            argv.extend(("--goal", request.task_query))
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            return MapperResult.failure(
                AdapterStatus.TIMEOUT, "MAPPER_TIMEOUT", str(exc)
            )
        except OSError as exc:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE, "MAPPER_UNAVAILABLE", str(exc)
            )
        if completed.returncode != 0:
            return MapperResult.failure(
                AdapterStatus.UNAVAILABLE,
                "MAPPER_EXECUTION_ERROR",
                completed.stderr.strip(),
            )
        try:
            value = _json_object_from_output(completed.stdout)
        except (TypeError, ValueError) as exc:
            return MapperResult.failure(
                AdapterStatus.INCOMPATIBLE_SCHEMA, "CLI_JSON_INVALID", str(exc)
            )
        return MapperResult.success(value)

    def refresh(self, request: SnapshotRequest) -> MapperResult[Mapping[str, Any]]:
        return self.create_or_resolve_snapshot(request)


def _json_object_from_output(output: str) -> Mapping[str, Any]:
    for line in reversed([
        line.strip() for line in output.splitlines() if line.strip()
    ]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ValueError("CLI did not return a JSON object")


def _version_from_output(output: str) -> str:
    try:
        value = _json_object_from_output(output)
    except ValueError:
        return ""
    for key in ("version", "component_version", "mapper_version"):
        if isinstance(value.get(key), str):
            return value[key]
    return ""


__all__ = [
    "AdapterStatus",
    "CachePolicy",
    "CacheStats",
    "CausalScope",
    "ContextSnapshotHandle",
    "ExpandedContext",
    "InstalledMapperBindingTransport",
    "MapperCapabilities",
    "MapperCliJsonTransport",
    "MapperClient",
    "MapperResult",
    "ResultMetrics",
    "SnapshotRequest",
]
