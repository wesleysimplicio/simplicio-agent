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

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class Verdict(str, Enum):
    """Truth class emitted by the watcher gate."""

    MEASURED = "MEASURED"
    CANON = "CANON"
    UNVERIFIED = "UNVERIFIED"
    FABRICATED = "FABRICATED"


VerdictName = Literal["MEASURED", "CANON", "UNVERIFIED", "FABRICATED"]

_UNVERIFIED_SOURCE_MARKERS = frozenset(
    {"external", "network", "llm", "model", "remote", "web"}
)


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

    @property
    def passed(self) -> bool:
        """Whether the result is strong enough to satisfy a watcher gate."""

        return self.verdict in {Verdict.MEASURED, Verdict.CANON} and self.matches

    @property
    def status(self) -> str:
        """String form convenient for JSON/UI consumers."""

        return self.verdict.value


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


def evaluate_watcher(*args: Any, **kwargs: Any) -> GateResult:
    """Short alias for :func:`compare_reported_to_recomputed`."""

    return compare_reported_to_recomputed(*args, **kwargs)


__all__ = [
    "GateResult",
    "Verdict",
    "VerdictName",
    "canonical_json",
    "compare_reported_to_recomputed",
    "evaluate_watcher",
    "has_explicit_consent",
]
