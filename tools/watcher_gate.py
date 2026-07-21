"""Small, deterministic watcher-gate primitives.

The gate compares a reported value with a value recomputed by a trusted local
caller.  Comparison is performed on canonical JSON, so mapping insertion order
and user-defined ``__eq__`` implementations cannot change the result.

Only local, deterministic observations can produce ``MEASURED`` or ``CANON``.
Results from external services, networks, or LLMs are always ``UNVERIFIED``;
matching text from an untrusted source is not evidence of local measurement.

Consent is deliberately non-recursive: only the literal boolean ``True`` is
accepted.  Nested mappings, lists, strings, and truthy user objects do not
silently grant consent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Mapping


class Verdict(str, Enum):
    """Truth class emitted by the watcher gate."""

    MEASURED = "MEASURED"
    CANON = "CANON"
    UNVERIFIED = "UNVERIFIED"
    FABRICATED = "FABRICATED"


class EvidenceKind(str, Enum):
    """Evidence shapes supported by this bounded local gate."""

    FILE = "file"
    HASH = "hash"
    COMMAND = "command"
    RESULT = "result"
    SUB_AGENT = "sub-agent"


VerdictName = Literal["MEASURED", "CANON", "UNVERIFIED", "FABRICATED"]

_UNVERIFIED_SOURCE_MARKERS = frozenset({
    "external",
    "network",
    "llm",
    "model",
    "remote",
    "web",
})


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation or raise ``TypeError``.

    The gate intentionally accepts JSON-shaped data only.  Values such as
    sets, open handles, and NaN are not deterministic evidence and are left for
    the caller to classify as ``UNVERIFIED``.
    """

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TypeError("watcher values must be deterministic JSON data") from exc


def has_explicit_consent(consent: Any) -> bool:
    """Return whether consent was granted directly and explicitly.

    This is intentionally *not* recursive and does not call arbitrary
    ``__bool__`` implementations: ``type(consent) is bool`` is the contract.
    """

    return type(consent) is bool and consent is True


def _source_is_unverified(source: Any) -> bool:
    normalized = str(getattr(source, "value", source)).strip().lower()
    tokens = {part for part in normalized.replace("-", "_").split("_") if part}
    return bool(tokens & _UNVERIFIED_SOURCE_MARKERS)


def _source_is_canonical(source: Any) -> bool:
    normalized = str(getattr(source, "value", source)).strip().lower()
    return normalized in {"canon", "canonical"}


@dataclass(frozen=True, slots=True)
class GateResult:
    """Immutable result of one watcher comparison."""

    verdict: Verdict
    matches: bool
    consented: bool
    reported_canonical: str | None = None
    recomputed_canonical: str | None = None
    reason: str = ""
    kind: EvidenceKind | None = None
    subject: str = ""

    @property
    def passed(self) -> bool:
        """Whether the result is strong enough to satisfy a watcher gate."""

        return self.verdict in {Verdict.MEASURED, Verdict.CANON} and self.matches

    @property
    def status(self) -> str:
        """String form convenient for JSON/UI consumers."""

        return self.verdict.value

    def to_dict(self) -> dict[str, Any]:
        """Return a stable receipt shape for ledgers and trajectory adapters."""

        return {
            "verdict": self.verdict.value,
            "matches": self.matches,
            "consented": self.consented,
            "reported": self.reported_canonical,
            "recomputed": self.recomputed_canonical,
            "reason": self.reason,
            "kind": self.kind.value if self.kind is not None else None,
            "subject": self.subject,
        }


@dataclass(frozen=True, slots=True)
class CommandObservation:
    """Stable command outcome; output is compared by SHA-256."""

    exit_code: int
    output_sha256: str

    @classmethod
    def from_output(cls, exit_code: int, output: bytes | str) -> "CommandObservation":
        payload = output if isinstance(output, bytes) else str(output).encode("utf-8")
        return cls(int(exit_code), hashlib.sha256(payload).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        return {"exit_code": self.exit_code, "output_sha256": self.output_sha256}


class ConsentError(ValueError):
    """Base class for explicit, non-recursive consent failures."""


class ConsentRequiredError(ConsentError):
    """Raised when an action has no direct boolean consent."""


class RecursiveConsentError(ConsentError):
    """Raised when a watcher or nested agent tries to authorize an action."""


@dataclass(frozen=True, slots=True)
class ActionAuthorization:
    principal: str
    depth: int
    action: str


def compare_reported_to_recomputed(
    reported: Any,
    recomputed: Any,
    *,
    source: Any = "measured",
    consent: Any = True,
    require_consent: bool = False,
) -> GateResult:
    """Compare reported and recomputed values without invoking either value.

    ``source`` is caller-provided provenance.  ``external``, ``network``, and
    ``llm`` (including compound names such as ``network_api``) are always
    ``UNVERIFIED``.  For trusted local data, equal canonical JSON is
    ``MEASURED`` or ``CANON`` and unequal data is ``FABRICATED``.
    """

    consented = has_explicit_consent(consent)
    if require_consent and not consented:
        return GateResult(
            Verdict.UNVERIFIED,
            matches=False,
            consented=False,
            reason="explicit consent is required",
        )

    try:
        reported_canonical = canonical_json(reported)
        recomputed_canonical = canonical_json(recomputed)
    except TypeError as exc:
        return GateResult(
            Verdict.UNVERIFIED,
            matches=False,
            consented=consented,
            reason=str(exc),
        )

    matches = reported_canonical == recomputed_canonical
    if _source_is_unverified(source):
        verdict = Verdict.UNVERIFIED
        reason = "external, network, and LLM results are not local evidence"
    elif not matches:
        verdict = Verdict.FABRICATED
        reason = "reported value differs from recomputed value"
    elif _source_is_canonical(source):
        verdict = Verdict.CANON
        reason = "reported value matches the canonical recomputation"
    else:
        verdict = Verdict.MEASURED
        reason = "reported value matches the local recomputation"

    return GateResult(
        verdict,
        matches=matches,
        consented=consented,
        reported_canonical=reported_canonical,
        recomputed_canonical=recomputed_canonical,
        reason=reason,
    )


def _with_context(result: GateResult, kind: EvidenceKind, subject: str) -> GateResult:
    return GateResult(
        result.verdict,
        matches=result.matches,
        consented=result.consented,
        reported_canonical=result.reported_canonical,
        recomputed_canonical=result.recomputed_canonical,
        reason=result.reason,
        kind=kind,
        subject=subject,
    )


def _unverified(
    kind: EvidenceKind, subject: str, reported: Any, reason: str
) -> GateResult:
    return GateResult(
        Verdict.UNVERIFIED,
        matches=False,
        consented=False,
        reported_canonical=None,
        recomputed_canonical=None,
        reason=reason,
        kind=kind,
        subject=subject,
    )


def _safe_file(root: str | Path, relative_path: str | Path) -> tuple[Path, str]:
    root_path = Path(root).expanduser().resolve()
    candidate = (root_path / Path(relative_path)).resolve()
    try:
        subject = candidate.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise ValueError("file evidence path escapes its workspace") from exc
    if not subject or subject == ".":
        raise ValueError("file evidence path must identify a file")
    return candidate, subject


def watch_file(
    root: str | Path,
    relative_path: str | Path,
    reported: Mapping[str, Any] | None,
) -> GateResult:
    """Re-hash one local regular file and compare its stable facts."""

    subject = str(relative_path)
    if not isinstance(reported, Mapping):
        return _unverified(
            EvidenceKind.FILE,
            subject,
            reported,
            "file claim must be an object with exists, size, and sha256",
        )
    try:
        path, subject = _safe_file(root, relative_path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _unverified(
            EvidenceKind.FILE,
            subject,
            reported,
            f"file could not be safely recomputed: {exc}",
        )
    try:
        if path.is_file():
            payload = path.read_bytes()
            recomputed = {
                "exists": True,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        else:
            recomputed = {"exists": False, "size": None, "sha256": None}
    except OSError as exc:
        return _unverified(
            EvidenceKind.FILE,
            subject,
            reported,
            f"file could not be read for recomputation: {exc}",
        )
    return _with_context(
        compare_reported_to_recomputed(dict(reported), recomputed),
        EvidenceKind.FILE,
        subject,
    )


def watch_hash(
    value: Any,
    reported: str | Mapping[str, Any] | None,
    *,
    algorithm: str = "sha256",
    subject: str = "value",
) -> GateResult:
    """Hash bytes, text, or canonical JSON and compare the reported digest."""

    normalized_algorithm = algorithm.lower().strip()
    if normalized_algorithm not in hashlib.algorithms_available:
        return _unverified(
            EvidenceKind.HASH,
            subject,
            reported,
            f"unsupported hash algorithm: {algorithm}",
        )
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        try:
            payload = canonical_json(value).encode("utf-8")
        except TypeError as exc:
            return _unverified(EvidenceKind.HASH, subject, reported, str(exc))
    digest = hashlib.new(normalized_algorithm, payload).hexdigest()
    recomputed = {"algorithm": normalized_algorithm, "digest": digest}
    if isinstance(reported, Mapping):
        normalized_reported: Any = {
            "algorithm": str(reported.get("algorithm", normalized_algorithm)).lower(),
            "digest": str(reported.get("digest", "")).lower(),
        }
    else:
        normalized_reported = {
            "algorithm": normalized_algorithm,
            "digest": str(reported or "").lower(),
        }
    return _with_context(
        compare_reported_to_recomputed(normalized_reported, recomputed),
        EvidenceKind.HASH,
        subject,
    )


def _command_observation(value: Any) -> CommandObservation | None:
    if isinstance(value, CommandObservation):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        exit_code = int(value["exit_code"])
        output_hash = value.get("output_sha256")
        if output_hash is None and "output" in value:
            output_hash = hashlib.sha256(
                str(value["output"]).encode("utf-8")
            ).hexdigest()
        if not isinstance(output_hash, str) or not output_hash:
            return None
        return CommandObservation(exit_code, output_hash.lower())
    except (KeyError, TypeError, ValueError):
        return None


def watch_command(
    command: str,
    reported: CommandObservation | Mapping[str, Any] | None,
    recompute: Callable[[], CommandObservation | Mapping[str, Any]] | None,
) -> GateResult:
    """Compare command evidence using one injected callback, never a subprocess.

    A missing or failing callback is ``UNVERIFIED``.  This makes fake exit
    codes observable in tests without implying that a real external command
    was run by this module.
    """

    normalized_reported = _command_observation(reported)
    if not str(command).strip():
        return _unverified(
            EvidenceKind.COMMAND,
            command,
            reported,
            "command claim has no command text",
        )
    if normalized_reported is None:
        return _unverified(
            EvidenceKind.COMMAND,
            command,
            reported,
            "command claim must include exit_code and output_sha256",
        )
    if recompute is None:
        return _unverified(
            EvidenceKind.COMMAND,
            command,
            reported,
            "no bounded command recompute callback was provided",
        )
    try:
        recomputed = _command_observation(recompute())
    except Exception as exc:  # noqa: BLE001 - never turn failure into a pass
        return _unverified(
            EvidenceKind.COMMAND,
            command,
            reported,
            f"command recomputation failed: {exc}",
        )
    if recomputed is None:
        return _unverified(
            EvidenceKind.COMMAND,
            command,
            reported,
            "command recompute returned an invalid observation",
        )
    return _with_context(
        compare_reported_to_recomputed(
            normalized_reported.to_dict(), recomputed.to_dict()
        ),
        EvidenceKind.COMMAND,
        command,
    )


def _boundary_kind(kind: str) -> EvidenceKind:
    normalized = str(kind).strip().lower().replace("_", "-")
    if normalized in {"sub-agent", "subagent", "child"}:
        return EvidenceKind.SUB_AGENT
    return EvidenceKind.RESULT


def watch_result_boundary(
    reported: Any,
    recompute: Callable[[], Any] | None,
    *,
    kind: str = "tool-result",
    subject: str = "result",
    source: Any = "measured",
) -> GateResult:
    """Watch a tool or sub-agent result at its return boundary.

    The caller supplies the independent recomputation callback.  This module
    never executes a command, calls an LLM, or treats a self-reported result
    as its own recomputation.  Missing callbacks therefore stay
    ``UNVERIFIED``; a deterministic mismatch is ``FABRICATED`` and is safe
    for the caller to block.
    """

    evidence_kind = _boundary_kind(kind)
    if not str(subject).strip():
        subject = "result"
    if recompute is None:
        return GateResult(
            Verdict.UNVERIFIED,
            matches=False,
            consented=False,
            reason="no independent recomputation is available at this boundary",
            kind=evidence_kind,
            subject=str(subject),
        )
    try:
        recomputed = recompute()
    except Exception as exc:  # noqa: BLE001 - a failed watcher is not a pass
        return GateResult(
            Verdict.UNVERIFIED,
            matches=False,
            consented=False,
            reason=f"independent recomputation failed: {exc}",
            kind=evidence_kind,
            subject=str(subject),
        )
    return _with_context(
        compare_reported_to_recomputed(
            reported,
            recomputed,
            source=source,
        ),
        evidence_kind,
        str(subject),
    )


def watcher_receipt(result: GateResult) -> dict[str, Any]:
    """Return the stable boundary receipt used by trajectories and ledgers."""

    provenance = (
        result.verdict.value
        if result.verdict in {Verdict.MEASURED, Verdict.CANON}
        else Verdict.UNVERIFIED.value
    )
    payload = result.to_dict()
    payload["provenance"] = provenance
    return payload


def authorize_action(
    action: str,
    *,
    principal: str,
    depth: int = 0,
    consent: Any = False,
) -> ActionAuthorization:
    """Allow consent only from the explicit depth-0 operator."""

    if not has_explicit_consent(consent):
        raise ConsentRequiredError("explicit operator consent is required")
    if principal != "operator" or depth != 0:
        raise RecursiveConsentError("only the depth-0 operator may authorize an action")
    if not str(action).strip():
        raise ValueError("action must be non-empty")
    return ActionAuthorization(principal=principal, depth=depth, action=action)


def evaluate_watcher(*args: Any, **kwargs: Any) -> GateResult:
    """Short alias for :func:`compare_reported_to_recomputed`."""

    return compare_reported_to_recomputed(*args, **kwargs)


__all__ = [
    "ActionAuthorization",
    "CommandObservation",
    "ConsentError",
    "ConsentRequiredError",
    "EvidenceKind",
    "GateResult",
    "RecursiveConsentError",
    "Verdict",
    "VerdictName",
    "authorize_action",
    "canonical_json",
    "compare_reported_to_recomputed",
    "evaluate_watcher",
    "has_explicit_consent",
    "watch_command",
    "watch_file",
    "watch_hash",
    "watch_result_boundary",
    "watcher_receipt",
]
