"""Typed effect interception contracts for a disposable shadow run.

The module is intentionally a boundary, not a second tool executor.  A caller
turns an effect into :class:`EffectRequest` before dispatching it.  In shadow
mode reads may be served by an explicitly supplied read-through callback;
mutations are recorded and either staged in a disposable overlay or blocked.
Unknown effect kinds are always blocked before a callback can run.

The repository-wide invocation choke point is still pending the #334/#228
decision.  Keeping this module standalone lets that integration happen without
moving snapshot ownership or adding model-tool surface area.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.transaction_primitives import SnapshotManifest, snapshot_tree


EFFECT_REQUEST_SCHEMA = "simplicio.effect-request/v1"
SHADOW_REPORT_SCHEMA = "simplicio.shadow-report/v1"
SHADOW_RECEIPT_SCHEMA = "simplicio.hbp-shadow-receipt/v1"
_MISSING = object()


class UnknownEffectError(ValueError):
    """Raised when input names an effect absent from the closed taxonomy."""


class EffectBlockedError(RuntimeError):
    """Raised by direct sentinel calls when an external effect is attempted."""


class EffectKind(str, Enum):
    """Closed set of effect classes that may cross the agent boundary."""

    FS_READ = "fs_read"
    FS_WRITE = "fs_write"
    PROCESS_EXEC = "process_exec"
    NETWORK_HTTP = "network_http"
    PROVIDER_REMOTE = "provider_remote"
    GITHUB_API = "github_api"
    PLATFORM_MESSAGE = "platform_message"
    STATE_WRITE = "state_write"
    # Descriptive aliases keep call sites readable while the wire vocabulary
    # remains one closed set.
    FILESYSTEM_READ = "fs_read"
    FILESYSTEM_WRITE = "fs_write"
    HTTP = "network_http"


_READ_THROUGH_KINDS = frozenset({EffectKind.FS_READ})
_WRITE_KINDS = frozenset(EffectKind) - _READ_THROUGH_KINDS


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("effect payload must be JSON serializable") from exc


def _effect_kind(value: EffectKind | str) -> EffectKind:
    if isinstance(value, EffectKind):
        return value
    try:
        return EffectKind(str(value).strip().casefold())
    except ValueError as exc:
        raise UnknownEffectError(f"unknown effect kind: {value!r}") from exc


def _request_id(
    effect: EffectKind, operation: str, target: str, payload: Mapping[str, Any]
) -> str:
    value = f"{effect.value}|{operation}|{target}|{_canonical(payload)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EffectRequest:
    """A deterministic, JSON-ready description of one effect attempt."""

    effect: EffectKind | str
    operation: str
    target: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    read_through: bool = False

    def __post_init__(self) -> None:
        effect = _effect_kind(self.effect)
        operation = str(self.operation).strip()
        target = str(self.target).strip()
        if not operation:
            raise ValueError("effect operation must be non-empty")
        if not isinstance(self.payload, Mapping):
            raise TypeError("effect payload must be a mapping")
        payload = json.loads(_canonical(dict(self.payload)))
        if self.read_through and effect not in _READ_THROUGH_KINDS:
            raise ValueError("only read effects may use read-through")
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "payload", payload)

    @property
    def kind(self) -> EffectKind:
        """Alias useful at choke points that call the field ``kind``."""

        return self.effect  # type: ignore[return-value]

    @property
    def is_read(self) -> bool:
        return self.effect in _READ_THROUGH_KINDS

    @property
    def request_id(self) -> str:
        return _request_id(self.effect, self.operation, self.target, self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EFFECT_REQUEST_SCHEMA,
            "effect": self.effect.value,
            "operation": self.operation,
            "target": self.target,
            "payload": dict(self.payload),
            "read_through": self.read_through,
            "request_id": self.request_id,
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectRequest":
        if value.get("schema", EFFECT_REQUEST_SCHEMA) != EFFECT_REQUEST_SCHEMA:
            raise ValueError("unsupported effect request schema")
        return cls(
            effect=value.get("effect", ""),
            operation=str(value.get("operation", "")),
            target=str(value.get("target", "")),
            payload=value.get("payload", {}),
            read_through=bool(value.get("read_through", False)),
        )


@dataclass(frozen=True)
class OverlayReceipt:
    """Evidence for a write staged below a disposable overlay root."""

    path: str
    operation: str
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "operation": self.operation, "applied": self.applied}


class ShadowOverlay:
    """A disposable filesystem overlay with strict relative-path handling."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise ValueError("overlay root must be a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipts: list[OverlayReceipt] = []

    @classmethod
    def from_snapshot(
        cls,
        store: Any,
        manifest: SnapshotManifest | str,
        root: str | Path,
    ) -> "ShadowOverlay":
        """Mount an existing transaction snapshot into a disposable root."""

        store.restore(manifest, Path(root))
        return cls(root)

    def _path(self, relative: str) -> Path:
        candidate = Path(str(relative))
        if (
            not str(relative).strip()
            or candidate.is_absolute()
            or ".." in candidate.parts
        ):
            raise ValueError("overlay path must stay within its root")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("overlay path must stay within its root") from exc
        return resolved

    def apply(self, request: EffectRequest) -> OverlayReceipt:
        """Stage a file write/delete; never writes outside ``root``."""

        if request.effect is not EffectKind.FS_WRITE:
            raise ValueError("overlay only accepts fs_write effects")
        relative = str(request.payload.get("path", request.target))
        destination = self._path(relative)
        operation = request.operation.casefold()
        if operation in {"write", "create", "replace"}:
            content = request.payload.get("content", _MISSING)
            if content is _MISSING:
                raise ValueError("overlay write requires payload.content")
            if isinstance(content, str):
                data = content.encode("utf-8")
            elif isinstance(content, bytes):
                data = content
            else:
                raise TypeError("overlay content must be text or bytes")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        elif operation in {"delete", "unlink", "remove"}:
            if destination.exists():
                if destination.is_dir():
                    raise ValueError("overlay delete cannot remove a directory")
                destination.unlink()
        else:
            raise ValueError(f"unsupported overlay operation: {request.operation!r}")
        receipt = OverlayReceipt(relative.replace("\\", "/"), operation, True)
        self.receipts.append(receipt)
        return receipt

    def read_bytes(self, relative: str) -> bytes:
        return self._path(relative).read_bytes()

    def discard(self) -> None:
        """Remove staged data; the caller owns the overlay directory lifecycle."""

        for child in tuple(self.root.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.receipts.clear()


@dataclass(frozen=True)
class EffectDecision:
    """The only result an interceptor exposes to an execution choke point."""

    request: EffectRequest | None
    disposition: str
    executed: bool
    blocked: bool
    reason: str = ""
    value: Any = None
    overlay: OverlayReceipt | None = None

    @property
    def allowed(self) -> bool:
        return not self.blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "executed": self.executed,
            "blocked": self.blocked,
            "reason": self.reason,
            "request": self.request.to_dict() if self.request else None,
            "overlay": self.overlay.to_dict() if self.overlay else None,
        }


class NetworkSentinel:
    """Record and block all network attempts made during shadow execution."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, str]] = []

    def block(self, request: EffectRequest, reason: str = "shadow mode") -> None:
        self.attempts.append({
            "request_id": request.request_id,
            "target": request.target,
            "reason": reason,
        })
        raise EffectBlockedError(
            f"network effect blocked: {request.target or request.operation}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "network",
            "passed": True,
            "blocked_attempts": list(self.attempts),
        }


@dataclass(frozen=True)
class FilesystemSentinel:
    """Before/after digest check proving a host tree did not drift."""

    root: Path
    before: SnapshotManifest
    after: SnapshotManifest | None = None

    @classmethod
    def capture(cls, root: str | Path) -> "FilesystemSentinel":
        path = Path(root).expanduser().resolve()
        return cls(path, snapshot_tree(path))

    def check(self) -> "FilesystemSentinel":
        return FilesystemSentinel(self.root, self.before, snapshot_tree(self.root))

    @property
    def passed(self) -> bool:
        return (
            self.after is not None and self.after.snapshot_id == self.before.snapshot_id
        )

    def to_dict(self) -> dict[str, Any]:
        after = self.after.snapshot_id if self.after else None
        return {
            "kind": "filesystem",
            "passed": self.passed,
            "before_digest": self.before.snapshot_id,
            "after_digest": after,
        }


class EffectInterceptor:
    """Record every request and fail closed for non-read effects in shadow mode."""

    def __init__(
        self,
        *,
        overlay: ShadowOverlay | None = None,
        network_sentinel: NetworkSentinel | None = None,
    ) -> None:
        self.overlay = overlay
        self.network_sentinel = network_sentinel or NetworkSentinel()
        self.requests: list[EffectRequest] = []
        self.decisions: list[EffectDecision] = []
        self.unknown_effects: list[Mapping[str, Any]] = []

    def intercept(
        self,
        request: EffectRequest | Mapping[str, Any],
        *,
        read_through: Callable[[EffectRequest], Any] | None = None,
    ) -> EffectDecision:
        """Record one request without executing an external mutation."""

        try:
            typed = (
                request
                if isinstance(request, EffectRequest)
                else EffectRequest.from_dict(request)
            )
        except (TypeError, ValueError, UnknownEffectError) as exc:
            if isinstance(request, Mapping):
                self.unknown_effects.append(dict(request))
            decision = EffectDecision(
                request=None,
                disposition="blocked",
                executed=False,
                blocked=True,
                reason=f"unknown or malformed effect: {exc}",
            )
            self.decisions.append(decision)
            return decision

        self.requests.append(typed)
        if typed.effect is EffectKind.FS_READ:
            if read_through is None:
                decision = EffectDecision(
                    typed, "blocked", False, True, "read-through callback is required"
                )
            else:
                decision = EffectDecision(
                    typed, "read_through", False, False, value=read_through(typed)
                )
        elif typed.effect is EffectKind.FS_WRITE and self.overlay is not None:
            decision = EffectDecision(
                typed, "overlay", False, False, overlay=self.overlay.apply(typed)
            )
        else:
            if typed.effect in {
                EffectKind.NETWORK_HTTP,
                EffectKind.PROVIDER_REMOTE,
                EffectKind.GITHUB_API,
                EffectKind.PLATFORM_MESSAGE,
            }:
                self.network_sentinel.attempts.append({
                    "request_id": typed.request_id,
                    "target": typed.target,
                    "reason": "shadow mode",
                })
            decision = EffectDecision(
                typed, "blocked", False, True, "external effect blocked in shadow mode"
            )
        self.decisions.append(decision)
        return decision


class DivergenceKind(str, Enum):
    ADDITION = "addition"
    MISSING = "missing"
    PAYLOAD = "payload"
    ORDER = "order"


@dataclass(frozen=True)
class EffectDivergence:
    kind: DivergenceKind
    index: int
    legacy: EffectRequest | None
    shadow: EffectRequest | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "index": self.index,
            "legacy": self.legacy.to_dict() if self.legacy else None,
            "shadow": self.shadow.to_dict() if self.shadow else None,
        }


@dataclass(frozen=True)
class DivergenceReport:
    """Machine-readable comparison of legacy and shadow request sequences."""

    legacy_count: int
    shadow_count: int
    divergences: tuple[EffectDivergence, ...] = ()

    @property
    def equivalent(self) -> bool:
        return not self.divergences

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHADOW_REPORT_SCHEMA,
            "legacy_count": self.legacy_count,
            "shadow_count": self.shadow_count,
            "equivalent": self.equivalent,
            "divergences": [item.to_dict() for item in self.divergences],
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def compare_effect_sequences(
    legacy: Sequence[EffectRequest | Mapping[str, Any]],
    shadow: Sequence[EffectRequest | Mapping[str, Any]],
) -> DivergenceReport:
    """Detect extra, missing, reordered, and payload-divergent effects."""

    left = tuple(
        item if isinstance(item, EffectRequest) else EffectRequest.from_dict(item)
        for item in legacy
    )
    right = tuple(
        item if isinstance(item, EffectRequest) else EffectRequest.from_dict(item)
        for item in shadow
    )
    divergences: list[EffectDivergence] = []
    # A permutation is one order divergence, not a payload mismatch at every
    # swapped index. This keeps the report useful for the four acceptance
    # cases and avoids double-counting one semantic difference.
    left_ids = tuple(item.request_id for item in left)
    right_ids = tuple(item.request_id for item in right)
    if len(left) == len(right) and set(left_ids) == set(right_ids):
        for index, (old_id, new_id) in enumerate(zip(left_ids, right_ids)):
            if old_id != new_id:
                return DivergenceReport(
                    len(left),
                    len(right),
                    (
                        EffectDivergence(
                            DivergenceKind.ORDER, index, left[index], right[index]
                        ),
                    ),
                )
        return DivergenceReport(len(left), len(right))
    for index in range(max(len(left), len(right))):
        old = left[index] if index < len(left) else None
        new = right[index] if index < len(right) else None
        if old is None:
            divergences.append(
                EffectDivergence(DivergenceKind.ADDITION, index, None, new)
            )
        elif new is None:
            divergences.append(
                EffectDivergence(DivergenceKind.MISSING, index, old, None)
            )
        elif old.request_id == new.request_id:
            continue
        elif old.request_id in {
            item.request_id for item in right[index + 1 :]
        } or new.request_id in {item.request_id for item in left[index + 1 :]}:
            divergences.append(EffectDivergence(DivergenceKind.ORDER, index, old, new))
        elif (
            old.effect == new.effect
            and old.operation == new.operation
            and old.target == new.target
        ):
            divergences.append(
                EffectDivergence(DivergenceKind.PAYLOAD, index, old, new)
            )
        else:
            divergences.append(
                EffectDivergence(DivergenceKind.PAYLOAD, index, old, new)
            )
    return DivergenceReport(len(left), len(right), tuple(divergences))


@dataclass(frozen=True)
class ShadowReceipt:
    """HBP-compatible proof envelope for one shadow-run decision."""

    snapshot_digest: str
    report: DivergenceReport
    filesystem: Mapping[str, Any]
    network: Mapping[str, Any]
    verdict: str = "pass"

    def __post_init__(self) -> None:
        if self.verdict not in {"pass", "fail", "blocked"}:
            raise ValueError("shadow verdict must be pass, fail, or blocked")
        if len(self.snapshot_digest) != 64:
            raise ValueError("snapshot_digest must be a sha256 digest")
        if self.verdict == "pass" and (
            not self.report.equivalent
            or not bool(self.filesystem.get("passed"))
            or not bool(self.network.get("passed"))
        ):
            raise ValueError(
                "passing shadow receipt requires equivalent effects and sentinels"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def _body_dict(self) -> dict[str, Any]:
        return {
            "schema": SHADOW_RECEIPT_SCHEMA,
            "hbp_schema": "simplicio.hbp-receipt/v1",
            "snapshot_digest": self.snapshot_digest,
            "report_digest": self.report.digest(),
            "report": self.report.to_dict(),
            "filesystem": dict(self.filesystem),
            "network": dict(self.network),
            "verdict": self.verdict,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._body_dict()
        value["receipt_digest"] = self.digest
        return value

    def to_json(self) -> str:
        return _canonical(self._body_dict())


__all__ = [
    "EFFECT_REQUEST_SCHEMA",
    "SHADOW_REPORT_SCHEMA",
    "SHADOW_RECEIPT_SCHEMA",
    "EffectKind",
    "EffectRequest",
    "UnknownEffectError",
    "EffectBlockedError",
    "EffectDecision",
    "ShadowOverlay",
    "OverlayReceipt",
    "NetworkSentinel",
    "FilesystemSentinel",
    "EffectInterceptor",
    "DivergenceKind",
    "EffectDivergence",
    "DivergenceReport",
    "compare_effect_sequences",
    "ShadowReceipt",
    "EffectType",
    "ShadowEffectInterceptor",
    "FileSystemSentinel",
]


# Compatibility spellings for the choke-point integration. They are aliases,
# not separate business logic or alternate wire vocabularies.
EffectType = EffectKind
ShadowEffectInterceptor = EffectInterceptor
FileSystemSentinel = FilesystemSentinel
