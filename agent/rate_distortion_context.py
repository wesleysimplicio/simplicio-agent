"""Bounded, additive rate-distortion checks for compressed context.

This module is an engineering contract, not an information-theory benchmark.
It scores observable context loss, rejects load-bearing loss, and keeps the
accepted source in a deterministic, reversible Context Compression Receipt
(CCR).  The implementation is deliberately dependency-free so it can sit on
the fast path of existing compressors without invoking an LLM.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import time
from typing import Any, Mapping, Pattern


SCHEMA = "rate-distortion-context/v1"
CCR_SCHEMA = "ccr/v1"
DEFAULT_WEIGHTS = {
    "ac_lost": 10.0,
    "refs_lost": 8.0,
    "numbers_changed": 8.0,
    "errors_hidden": 12.0,
    "answer_delta": 1.0,
}

_AC_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:AC(?:[-_ ]?\d+)|ACCEPTANCE[-_ ]+CRITER(?:IA|ION)[-_ :#]*\d+)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s`'\"<>]+", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|/|~/)[^\s`'\"<>]+")
_REL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_-]+)?"
)
_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(?<!`)`(?!`)([^`\n]+)`(?!`)")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:v?\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.-]+)?|v?\d+)(?![A-Za-z0-9_.])",
    re.IGNORECASE,
)
_ERROR_LINE_RE = re.compile(r"^\s*(?:ERROR|WARNING)\b[^\n]*", re.IGNORECASE | re.MULTILINE)
_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def _canonical_json(value: Any) -> str:
    """Serialize JSON without process-, locale-, or insertion-order drift."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_json(value: Any) -> str:
    """Public deterministic JSON serializer used by receipts and callers."""

    return _canonical_json(value)


def _to_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("context must be str or bytes")


def _to_text(value: str | bytes) -> str:
    return value if isinstance(value, str) else value.decode("utf-8", errors="replace")


def _tokens(value: str | bytes) -> int:
    size = len(_to_bytes(value))
    return (size + 3) // 4


def _missing(before: list[str], after: list[str]) -> int:
    remaining = Counter(after)
    missing = 0
    for item in before:
        if remaining[item]:
            remaining[item] -= 1
        else:
            missing += 1
    return missing


def _paths(text: str) -> list[str]:
    urls = set(_URL_RE.findall(text))
    values = _ABS_PATH_RE.findall(text) + _REL_PATH_RE.findall(text)
    return [value for value in values if value not in urls]


def _features(value: str | bytes) -> dict[str, list[str]]:
    text = _to_text(value)
    return {
        "ac": _AC_RE.findall(text),
        "urls": _URL_RE.findall(text),
        "paths": _paths(text),
        "inline_code": [match.group(0) for match in _INLINE_CODE_RE.finditer(text)],
        "fenced_code": _FENCE_RE.findall(text),
        "numbers": _NUMBER_RE.findall(text),
        "errors": _ERROR_LINE_RE.findall(text),
    }


@dataclass(frozen=True)
class FidelityBudget:
    """Finite acceptance limits for one compression decision."""

    epsilon: float = 0.0
    token_budget: int | None = None
    max_rate: float = 1.0
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    ttl_seconds: int = 86_400
    policy: str = "retain-original"

    def __post_init__(self) -> None:
        if not math.isfinite(self.epsilon) or self.epsilon < 0:
            raise ValueError("epsilon must be finite and non-negative")
        if not math.isfinite(self.max_rate) or self.max_rate <= 0:
            raise ValueError("max_rate must be finite and positive")
        if self.token_budget is not None and (
            isinstance(self.token_budget, bool) or self.token_budget <= 0
        ):
            raise ValueError("token_budget must be a positive integer or None")
        if isinstance(self.ttl_seconds, bool) or self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not self.policy.strip():
            raise ValueError("policy must not be empty")
        for key, weight in self.weights.items():
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(f"weight {key!r} must be finite and non-negative")

    def weight_for(self, category: str) -> float:
        return float(self.weights.get(category, 0.0))


@dataclass(frozen=True)
class CompressionLoss:
    """Observable loss vector and its additive engineering distortion."""

    ac_lost: int = 0
    refs_lost: int = 0
    numbers_changed: int = 0
    errors_hidden: int = 0
    answer_delta: float = 0.0
    hard_failure: bool = False
    reason_codes: tuple[str, ...] = ()
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        for name in ("ac_lost", "refs_lost", "numbers_changed", "errors_hidden"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not math.isfinite(self.answer_delta) or not 0 <= self.answer_delta <= 1:
            raise ValueError("answer_delta must be finite and between 0 and 1")

    @property
    def distortion(self) -> float:
        values = {
            "ac_lost": self.ac_lost,
            "refs_lost": self.refs_lost,
            "numbers_changed": self.numbers_changed,
            "errors_hidden": self.errors_hidden,
            "answer_delta": self.answer_delta,
        }
        total = sum(float(self.weights.get(key, 0.0)) * value for key, value in values.items())
        return math.inf if self.hard_failure else total

    @property
    def D(self) -> float:  # noqa: N802 - mirrors the issue's contract notation.
        return self.distortion

    def as_dict(self) -> dict[str, Any]:
        return {
            "ac_lost": self.ac_lost,
            "refs_lost": self.refs_lost,
            "numbers_changed": self.numbers_changed,
            "errors_hidden": self.errors_hidden,
            "answer_delta": self.answer_delta,
            "hard_failure": self.hard_failure,
            "reason_codes": list(self.reason_codes),
            "distortion": self.distortion,
        }


def score_compression(
    original: str | bytes,
    compressed: str | bytes,
    *,
    weights: Mapping[str, float] | None = None,
) -> CompressionLoss:
    """Score a candidate by multiset loss of protected markers and words."""

    before = _features(original)
    after = _features(compressed)
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    reason_codes: set[str] = set()

    ac_lost = _missing(before["ac"], after["ac"])
    refs_lost = 0
    for category, reason in (
        ("urls", "url_lost"),
        ("paths", "path_lost"),
        ("inline_code", "inline_code_lost"),
        ("fenced_code", "fenced_code_lost"),
    ):
        lost = _missing(before[category], after[category])
        refs_lost += lost
        if lost:
            reason_codes.add(reason)
    numbers_changed = _missing(before["numbers"], after["numbers"])
    errors_hidden = _missing(before["errors"], after["errors"])
    if ac_lost:
        reason_codes.add("ac_lost")
    if numbers_changed:
        reason_codes.add("number_changed")
    if errors_hidden:
        reason_codes.add("error_or_warning_hidden")

    before_words = Counter(_WORD_RE.findall(_to_text(original).casefold()))
    after_words = Counter(_WORD_RE.findall(_to_text(compressed).casefold()))
    missing_words = sum(max(0, count - after_words[word]) for word, count in before_words.items())
    answer_delta = min(1.0, missing_words / max(1, sum(before_words.values())))
    hard_failure = bool(ac_lost or refs_lost or numbers_changed or errors_hidden)
    return CompressionLoss(
        ac_lost=ac_lost,
        refs_lost=refs_lost,
        numbers_changed=numbers_changed,
        errors_hidden=errors_hidden,
        answer_delta=answer_delta,
        hard_failure=hard_failure,
        reason_codes=tuple(sorted(reason_codes)),
        weights=weights,
    )


score_context = score_compression


def _receipt_handle(original_sha256: str, compressed_sha256: str, policy: str, ttl_seconds: int) -> str:
    identity = _canonical_json(
        {
            "compressed_sha256": compressed_sha256,
            "original_sha256": original_sha256,
            "policy": policy,
            "schema": CCR_SCHEMA,
            "ttl_seconds": ttl_seconds,
        }
    ).encode("utf-8")
    return f"ccr:v1:{hashlib.sha256(identity).hexdigest()}"


@dataclass(frozen=True)
class CCRReceipt:
    """A deterministic receipt retaining the exact pre-compression bytes."""

    handle: str
    original_bytes: bytes = field(repr=False)
    compressed_bytes: bytes = field(repr=False)
    original_sha256: str
    compressed_sha256: str
    ttl_seconds: int
    policy: str
    original_is_text: bool = True
    loss: CompressionLoss = field(default_factory=CompressionLoss, repr=False)
    schema: str = CCR_SCHEMA

    @classmethod
    def create(
        cls,
        original: str | bytes,
        compressed: str | bytes,
        *,
        budget: FidelityBudget,
        loss: CompressionLoss,
    ) -> "CCRReceipt":
        original_bytes = _to_bytes(original)
        compressed_bytes = _to_bytes(compressed)
        original_sha256 = hashlib.sha256(original_bytes).hexdigest()
        compressed_sha256 = hashlib.sha256(compressed_bytes).hexdigest()
        handle = _receipt_handle(
            original_sha256, compressed_sha256, budget.policy, budget.ttl_seconds
        )
        return cls(
            handle=handle,
            original_bytes=original_bytes,
            compressed_bytes=compressed_bytes,
            original_sha256=original_sha256,
            compressed_sha256=compressed_sha256,
            ttl_seconds=budget.ttl_seconds,
            policy=budget.policy,
            original_is_text=isinstance(original, str),
            loss=loss,
        )

    def __post_init__(self) -> None:
        if self.schema != CCR_SCHEMA:
            raise ValueError("unsupported CCR schema")
        if hashlib.sha256(self.original_bytes).hexdigest() != self.original_sha256:
            raise ValueError("original CCR hash mismatch")
        if hashlib.sha256(self.compressed_bytes).hexdigest() != self.compressed_sha256:
            raise ValueError("compressed CCR hash mismatch")
        expected = _receipt_handle(
            self.original_sha256, self.compressed_sha256, self.policy, self.ttl_seconds
        )
        if self.handle != expected:
            raise ValueError("CCR handle mismatch")

    @property
    def original(self) -> str | bytes:
        return self.original_bytes.decode("utf-8") if self.original_is_text else self.original_bytes

    @property
    def compressed(self) -> str | bytes:
        return self.compressed_bytes.decode("utf-8") if self.original_is_text else self.compressed_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "compressed_b64": base64.b64encode(self.compressed_bytes).decode("ascii"),
            "compressed_sha256": self.compressed_sha256,
            "handle": self.handle,
            "loss": self.loss.as_dict(),
            "original_b64": base64.b64encode(self.original_bytes).decode("ascii"),
            "original_is_text": self.original_is_text,
            "original_sha256": self.original_sha256,
            "policy": self.policy,
            "schema": self.schema,
            "ttl_seconds": self.ttl_seconds,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    serialize = to_json

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CCRReceipt":
        raw_loss = payload.get("loss") or {}
        loss = CompressionLoss(
            ac_lost=int(raw_loss.get("ac_lost", 0)),
            refs_lost=int(raw_loss.get("refs_lost", 0)),
            numbers_changed=int(raw_loss.get("numbers_changed", 0)),
            errors_hidden=int(raw_loss.get("errors_hidden", 0)),
            answer_delta=float(raw_loss.get("answer_delta", 0.0)),
            hard_failure=bool(raw_loss.get("hard_failure", False)),
            reason_codes=tuple(str(item) for item in raw_loss.get("reason_codes", ())),
        )
        return cls(
            handle=str(payload["handle"]),
            original_bytes=base64.b64decode(payload["original_b64"], validate=True),
            compressed_bytes=base64.b64decode(payload["compressed_b64"], validate=True),
            original_sha256=str(payload["original_sha256"]),
            compressed_sha256=str(payload["compressed_sha256"]),
            ttl_seconds=int(payload["ttl_seconds"]),
            policy=str(payload["policy"]),
            original_is_text=bool(payload.get("original_is_text", True)),
            loss=loss,
            schema=str(payload.get("schema", "")),
        )

    @classmethod
    def from_json(cls, payload: str) -> "CCRReceipt":
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("CCR JSON must contain an object")
        return cls.from_dict(value)

    def recover(
        self,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        pattern: str | Pattern[str] | None = None,
        flags: int = 0,
    ) -> str | bytes:
        """Recover the original, optionally restricted to 1-based lines."""

        if start_line is None and end_line is None and pattern is None:
            return self.original
        if start_line is not None and start_line < 1:
            raise ValueError("start_line must be 1 or greater")
        if end_line is not None and end_line < 1:
            raise ValueError("end_line must be 1 or greater")
        if start_line is not None and end_line is not None and start_line > end_line:
            raise ValueError("start_line must not exceed end_line")
        text = self.original_bytes.decode("utf-8")
        lines = text.splitlines(keepends=True)
        first = (start_line or 1) - 1
        last = end_line if end_line is not None else len(lines)
        selected = lines[first:last]
        if pattern is not None:
            matcher = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
            selected = [line for line in selected if matcher.search(line)]
        result = "".join(selected)
        return result if self.original_is_text else result.encode("utf-8")

    def recover_by_lines(self, start_line: int = 1, end_line: int | None = None) -> str | bytes:
        return self.recover(start_line=start_line, end_line=end_line)

    def recover_by_pattern(self, pattern: str, *, flags: int = 0) -> str | bytes:
        return self.recover(pattern=pattern, flags=flags)


class CCRStore:
    """Small in-memory CCR index with injectable time for deterministic tests."""

    def __init__(self) -> None:
        self._receipts: dict[str, tuple[CCRReceipt, float]] = {}

    def put(self, receipt: CCRReceipt, *, now: float = 0.0) -> str:
        self._receipts[receipt.handle] = (receipt, float(now))
        return receipt.handle

    def get(self, handle: str, *, now: float | None = None) -> CCRReceipt | None:
        stored = self._receipts.get(handle)
        if stored is None:
            return None
        receipt, inserted_at = stored
        if now is not None and float(now) >= inserted_at + receipt.ttl_seconds:
            self._receipts.pop(handle, None)
            return None
        return receipt

    def recover(self, handle: str, **kwargs: Any) -> str | bytes:
        receipt = self.get(handle, now=kwargs.pop("now", None))
        if receipt is None:
            raise KeyError(handle)
        return receipt.recover(**kwargs)


@dataclass(frozen=True)
class FidelityResult:
    accepted: bool
    output: str | bytes
    loss: CompressionLoss
    receipt: CCRReceipt | None
    original_tokens: int
    compressed_tokens: int
    rate: float
    reason_codes: tuple[str, ...] = ()


class FidelityRejected(ValueError):
    """Raised by ``FidelityGate.require`` when a candidate is not admissible."""

    def __init__(self, result: FidelityResult) -> None:
        self.result = result
        super().__init__("compression rejected: " + ", ".join(result.reason_codes))


class FidelityGate:
    """Admit only bounded, reversible compression candidates."""

    def __init__(self, budget: FidelityBudget, *, store: CCRStore | None = None) -> None:
        self.budget = budget
        self.store = store or CCRStore()

    def evaluate(self, original: str | bytes, compressed: str | bytes) -> FidelityResult:
        original_tokens = _tokens(original) if isinstance(original, (str, bytes)) else 0
        compressed_tokens = _tokens(compressed) if isinstance(compressed, (str, bytes)) else 0
        try:
            loss = score_compression(
                original,
                compressed,
                weights=self.budget.weights,
            )
        except (TypeError, UnicodeError, ValueError):
            loss = CompressionLoss(hard_failure=True, reason_codes=("invalid_input",))
            return FidelityResult(
                accepted=False,
                output=original,
                loss=loss,
                receipt=None,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                rate=math.inf,
                reason_codes=("invalid_input",),
            )

        rate = compressed_tokens / original_tokens if original_tokens else (0.0 if not compressed_tokens else math.inf)
        reasons = set(loss.reason_codes)
        if loss.hard_failure:
            reasons.add("hard_fidelity_failure")
        if not math.isfinite(loss.distortion) or loss.distortion > self.budget.epsilon:
            reasons.add("distortion_budget_exceeded")
        if rate > self.budget.max_rate:
            reasons.add("compression_rate_exceeded")
        if self.budget.token_budget is not None and compressed_tokens > self.budget.token_budget:
            reasons.add("token_budget_exceeded")
        if reasons:
            return FidelityResult(
                accepted=False,
                output=original,
                loss=loss,
                receipt=None,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                rate=rate,
                reason_codes=tuple(sorted(reasons)),
            )

        receipt = CCRReceipt.create(original, compressed, budget=self.budget, loss=loss)
        self.store.put(receipt)
        return FidelityResult(
            accepted=True,
            output=compressed,
            loss=loss,
            receipt=receipt,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            rate=rate,
            reason_codes=(),
        )

    check = evaluate

    def require(self, original: str | bytes, compressed: str | bytes) -> FidelityResult:
        result = self.evaluate(original, compressed)
        if not result.accepted:
            raise FidelityRejected(result)
        return result


__all__ = [
    "CCRReceipt",
    "CCRStore",
    "CompressionLoss",
    "DEFAULT_WEIGHTS",
    "FidelityBudget",
    "FidelityGate",
    "FidelityRejected",
    "FidelityResult",
    "SCHEMA",
    "canonical_json",
    "score_compression",
    "score_context",
]
