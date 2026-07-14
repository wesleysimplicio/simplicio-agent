"""Fail-closed equivalence gate and profile/session canary boundary.

The gate is deliberately an offline boundary.  It compares supplied shadow
reports; it does not run the candidate or claim that a report is production
evidence.  The flag store is equally small and conservative: an enabled flag
must be present in a valid document, scoped to an exact profile, and (when a
session is supplied) to that profile's exact session.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

EQUIVALENCE_SCHEMA = "simplicio.equivalence-gate/v1"
SHADOW_REPORT_SCHEMA = "simplicio.shadow-report/v1"
FLAG_SCHEMA = "simplicio.equivalence-flags/v1"
CANARY_EVENT_SCHEMA = "simplicio.equivalence-canary-event/v1"
VERSION = 1

DIMENSIONS = ("behavior", "tokens", "latency", "memory", "receipts")
SEVERITIES = frozenset({"blocking", "observation"})
DEFAULT_TOLERANCES = {
    "behavior": 0.0,
    "tokens": 0.0,
    "latency": 0.10,
    "memory": 0.10,
    "receipts": 0.0,
}
DEFAULT_SEVERITIES = {dimension: "blocking" for dimension in DIMENSIONS}


def canonical_json(value: Any) -> str:
    """Return the stable representation used for behavior comparisons."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_effect_request(value: Any) -> Any:
    """Normalize JSON-compatible EffectRequest data without changing meaning."""

    if isinstance(value, Mapping):
        return {
            str(key): normalize_effect_request(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [normalize_effect_request(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_effect_request(item) for item in value]
    return value


@dataclass(frozen=True)
class DimensionTolerance:
    """One relative tolerance and its gate severity."""

    limit: float
    severity: str = "blocking"

    def __post_init__(self) -> None:
        if self.limit < 0 or self.severity not in SEVERITIES:
            raise ValueError(
                "tolerance limit must be non-negative and severity must be valid"
            )


def _tolerances(value: Mapping[str, Any] | None) -> dict[str, DimensionTolerance]:
    result = {
        dimension: DimensionTolerance(
            DEFAULT_TOLERANCES[dimension], DEFAULT_SEVERITIES[dimension]
        )
        for dimension in DIMENSIONS
    }
    for dimension, raw in (value or {}).items():
        if dimension not in DIMENSIONS:
            raise ValueError(f"unknown equivalence dimension: {dimension}")
        if isinstance(raw, Mapping):
            limit = raw.get("limit", DEFAULT_TOLERANCES[dimension])
            severity = raw.get("severity", DEFAULT_SEVERITIES[dimension])
        else:
            limit = raw
            severity = DEFAULT_SEVERITIES[dimension]
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            raise ValueError(f"{dimension} tolerance must be numeric")
        numeric_limit = float(limit)
        if not math.isfinite(numeric_limit):
            raise ValueError(f"{dimension} tolerance must be finite")
        result[dimension] = DimensionTolerance(numeric_limit, str(severity))
    return result


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def _relative_delta(baseline: Any, candidate: Any, field: str) -> float:
    before = _number(baseline, field)
    after = _number(candidate, field)
    if before < 0 or after < 0:
        raise ValueError(f"{field} must be non-negative")
    if before == 0:
        return 0.0 if after == 0 else float("inf")
    return (after - before) / before


def _dimension_payload(row: Mapping[str, Any], side: str, dimension: str) -> Any:
    value = row.get(side)
    if not isinstance(value, Mapping):
        raise ValueError(f"{side} must be an object")
    dimensions = value.get("dimensions")
    if isinstance(dimensions, Mapping) and dimension in dimensions:
        return dimensions[dimension]
    if dimension in value:
        return value[dimension]
    raise ValueError(f"{side}.{dimension} is required")


def _metric(value: Any, dimension: str) -> float:
    if isinstance(value, Mapping):
        if dimension == "latency":
            for key in ("p95", "p95_ms", "p95_us", "latency_p95"):
                if key in value:
                    return _number(value[key], f"{dimension}.{key}")
        if dimension == "memory":
            for key in ("peak_memory_bytes", "peak", "bytes"):
                if key in value:
                    return _number(value[key], f"{dimension}.{key}")
        for key in ("value", "count", "tokens"):
            if key in value:
                return _number(value[key], f"{dimension}.{key}")
    return _number(value, dimension)


def _receipt_projection(value: Any) -> tuple[Any, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("receipts must be objects")
    schema = value.get("schema")
    required = value.get("required_fields", value.get("required", value.get("fields")))
    if not isinstance(schema, str) or not schema.strip():
        raise ValueError("receipts.schema must be a non-empty string")
    if not isinstance(required, list) or not all(
        isinstance(item, str) for item in required
    ):
        raise ValueError("receipts.required_fields must be a list of strings")
    return schema, sorted(required)


def compare_shadow_row(
    row: Mapping[str, Any],
    tolerances: Mapping[str, DimensionTolerance] | None = None,
) -> dict[str, Any]:
    """Compare one baseline/candidate shadow row and return dimension results."""

    specs = dict(tolerances or _tolerances(None))
    fixture_id = row.get("fixture_id", row.get("id", "unknown"))
    category = row.get("category", "uncategorized")
    results: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        spec = specs[dimension]
        try:
            before = _dimension_payload(row, "baseline", dimension)
            after = _dimension_payload(row, "candidate", dimension)
            if dimension == "behavior":
                before_normalized = normalize_effect_request(before)
                after_normalized = normalize_effect_request(after)
                observed = 0.0 if before_normalized == after_normalized else 1.0
                passed = observed <= spec.limit
                details = {"baseline": before_normalized, "candidate": after_normalized}
            elif dimension == "receipts":
                before_projection = _receipt_projection(before)
                after_projection = _receipt_projection(after)
                observed = 0.0 if before_projection == after_projection else 1.0
                passed = observed <= spec.limit
                details = {"baseline": before_projection, "candidate": after_projection}
            else:
                before_value = _metric(before, dimension)
                after_value = _metric(after, dimension)
                observed = _relative_delta(before_value, after_value, dimension)
                passed = observed <= spec.limit
                details = {"baseline": before_value, "candidate": after_value}
            results[dimension] = {
                "passed": passed,
                "observed_delta": observed,
                "tolerance": spec.limit,
                "severity": spec.severity,
                **details,
            }
        except (TypeError, ValueError, KeyError) as exc:
            results[dimension] = {
                "passed": False,
                "observed_delta": None,
                "tolerance": spec.limit,
                "severity": "blocking",
                "error": str(exc),
            }
    return {"fixture_id": fixture_id, "category": category, "dimensions": results}


def _reason(
    row: Mapping[str, Any], dimension: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    code = (
        "dimension_out_of_tolerance"
        if "error" not in result
        else "invalid_shadow_dimension"
    )
    return {
        "code": code,
        "dimension": dimension,
        "fixture_id": row["fixture_id"],
        "category": row["category"],
        "severity": result["severity"],
        "observed_delta": result.get("observed_delta"),
        "tolerance": result.get("tolerance"),
        **({"error": result["error"]} if "error" in result else {}),
    }


def evaluate_shadow_reports(
    reports: list[Mapping[str, Any]],
    *,
    tolerances: Mapping[str, Any] | None = None,
    expected_schema: str = SHADOW_REPORT_SCHEMA,
) -> dict[str, Any]:
    """Aggregate N shadow rows and return a fail-closed promotion verdict."""

    specs = _tolerances(tolerances)
    rows: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    if not isinstance(reports, list) or not reports:
        validation_errors.append("reports must be a non-empty list")
    else:
        for index, report in enumerate(reports):
            if not isinstance(report, Mapping):
                validation_errors.append(f"reports[{index}] must be an object")
                continue
            schema = report.get("schema")
            if schema != expected_schema:
                validation_errors.append(
                    f"reports[{index}].schema must be {expected_schema}"
                )
                continue
            try:
                compared = compare_shadow_row(report, specs)
            except (TypeError, ValueError, KeyError) as exc:
                validation_errors.append(f"reports[{index}] invalid: {exc}")
                continue
            rows.append(compared)
            for dimension, result in compared["dimensions"].items():
                if not result["passed"]:
                    reasons.append(_reason(compared, dimension, result))

    categories: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = row["category"]
        summary = categories.setdefault(category, {"sample_count": 0, "dimensions": {}})
        summary["sample_count"] += 1
        for dimension, result in row["dimensions"].items():
            dim_summary = summary["dimensions"].setdefault(
                dimension, {"passed": 0, "failed": 0, "max_delta": 0.0}
            )
            if result["passed"]:
                dim_summary["passed"] += 1
            else:
                dim_summary["failed"] += 1
            observed = result.get("observed_delta")
            if isinstance(observed, (int, float)):
                dim_summary["max_delta"] = max(dim_summary["max_delta"], observed)

    for error in validation_errors:
        reasons.append({
            "code": "invalid_shadow_report",
            "severity": "blocking",
            "error": error,
        })
    blocking = [reason for reason in reasons if reason.get("severity") == "blocking"]
    observations = [
        reason for reason in reasons if reason.get("severity") == "observation"
    ]
    verdict = "reject" if blocking else ("hold" if observations else "promote")
    return {
        "schema": EQUIVALENCE_SCHEMA,
        "version": VERSION,
        "verdict": verdict,
        "promote": verdict == "promote",
        "report_count": len(rows),
        "dimension_count": len(DIMENSIONS),
        "dimensions": list(DIMENSIONS),
        "tolerances": {
            name: {"limit": spec.limit, "severity": spec.severity}
            for name, spec in specs.items()
        },
        "categories": categories,
        "reasons": reasons,
        "evidence": "UNVERIFIED|offline comparison of supplied shadow reports; no live canary evidence",
    }


def evaluate_gate(reports: list[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Compatibility-friendly alias for callers that call this boundary a gate."""

    return evaluate_shadow_reports(reports, **kwargs)


def _flag_key(slice_name: str) -> str:
    name = slice_name.removeprefix("native.slice.")
    if not name or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in name
    ):
        raise ValueError("slice name must be a non-empty canonical identifier")
    return f"native.slice.{name}"


def _valid_flag_document(document: Any) -> bool:
    if (
        not isinstance(document, Mapping)
        or document.get("schema") != FLAG_SCHEMA
        or document.get("version") != VERSION
    ):
        return False
    flags = document.get("flags")
    if not isinstance(flags, Mapping):
        return False
    for key, value in flags.items():
        if (
            not isinstance(key, str)
            or not key.startswith("native.slice.")
            or not isinstance(value, Mapping)
        ):
            return False
        profiles = value.get("profiles")
        if not isinstance(profiles, Mapping):
            return False
        for profile_id, profile in profiles.items():
            if (
                not isinstance(profile_id, str)
                or not isinstance(profile, Mapping)
                or not isinstance(profile.get("enabled"), bool)
            ):
                return False
            sessions = profile.get("sessions", {})
            if not isinstance(sessions, Mapping) or any(
                not isinstance(session, str) or not isinstance(enabled, bool)
                for session, enabled in sessions.items()
            ):
                return False
    return True


class FeatureFlagStore:
    """A JSON flag store whose read path always fails closed."""

    def __init__(
        self, state_root: str | Path, filename: str = "equivalence-flags.json"
    ) -> None:
        self.state_root = Path(state_root)
        self.path = self.state_root / filename

    def _read(self) -> Mapping[str, Any] | None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return document if _valid_flag_document(document) else None

    def is_enabled(
        self, slice_name: str, *, profile_id: str | None, session_id: str | None
    ) -> bool:
        """Return true only for a valid exact profile/session scope."""

        if (
            not isinstance(profile_id, str)
            or not profile_id
            or not isinstance(session_id, str)
            or not session_id
        ):
            return False
        try:
            key = _flag_key(slice_name)
        except ValueError:
            return False
        document = self._read()
        if document is None:
            return False
        profile = document["flags"].get(key, {}).get("profiles", {}).get(profile_id)
        if not isinstance(profile, Mapping):
            return False
        sessions = profile.get("sessions", {})
        if session_id in sessions:
            return sessions[session_id] is True
        return profile.get("enabled") is True

    enabled = is_enabled
    read_flag = is_enabled

    def set_enabled(
        self, slice_name: str, *, profile_id: str, session_id: str, enabled: bool
    ) -> None:
        """Atomically write one exact profile/session pin."""

        if not profile_id or not session_id or not isinstance(enabled, bool):
            raise ValueError("profile_id, session_id, and enabled are required")
        key = _flag_key(slice_name)
        document = copy.deepcopy(
            self._read() or {"schema": FLAG_SCHEMA, "version": VERSION, "flags": {}}
        )
        entry = document["flags"].setdefault(key, {"profiles": {}})
        profile = entry["profiles"].setdefault(
            profile_id, {"enabled": False, "sessions": {}}
        )
        profile.setdefault("sessions", {})[session_id] = enabled
        self.state_root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.state_root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class CanaryController:
    """Activate or revoke a pinned canary and journal every transition."""

    def __init__(
        self, store: FeatureFlagStore, journal_path: str | Path, slice_name: str
    ) -> None:
        self.store = store
        self.journal_path = Path(journal_path)
        self.slice_name = _flag_key(slice_name)

    def _journal(
        self, profile_id: str, session_id: str, enabled: bool, reason: str
    ) -> None:
        event = {
            "schema": CANARY_EVENT_SCHEMA,
            "version": VERSION,
            "event": "canary_transition",
            "slice": self.slice_name,
            "profile_id": profile_id,
            "session_id": session_id,
            "enabled": enabled,
            "reason": reason,
        }
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(event) + "\n")

    def transition(
        self, profile_id: str, session_id: str, *, enabled: bool, reason: str
    ) -> bool:
        previous = self.store.is_enabled(
            self.slice_name, profile_id=profile_id, session_id=session_id
        )
        self.store.set_enabled(
            self.slice_name,
            profile_id=profile_id,
            session_id=session_id,
            enabled=enabled,
        )
        try:
            self._journal(profile_id, session_id, enabled, reason)
        except (OSError, ValueError):
            # Do not leave an activation behind without its transition receipt.
            self.store.set_enabled(
                self.slice_name,
                profile_id=profile_id,
                session_id=session_id,
                enabled=previous,
            )
            return False
        return True

    def activate(
        self, profile_id: str, session_id: str, *, reason: str = "canary_activate"
    ) -> bool:
        return self.transition(profile_id, session_id, enabled=True, reason=reason)

    def rollback_on_divergence(
        self,
        profile_id: str,
        session_id: str,
        *,
        divergence_rate: float,
        threshold: float,
    ) -> bool:
        if divergence_rate < 0 or threshold < 0:
            raise ValueError("divergence_rate and threshold must be non-negative")
        if divergence_rate <= threshold:
            return False
        return self.transition(
            profile_id,
            session_id,
            enabled=False,
            reason="divergence_threshold_exceeded",
        )


FlagStore = FeatureFlagStore


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("shadow report must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate_shadow_reports([_read_json(path) for path in args.reports])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": EQUIVALENCE_SCHEMA,
            "version": VERSION,
            "verdict": "reject",
            "reasons": [
                {
                    "code": "invalid_shadow_report",
                    "severity": "blocking",
                    "error": str(exc),
                }
            ],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "promote" else 1


__all__ = [
    "CANARY_EVENT_SCHEMA",
    "DIMENSIONS",
    "EQUIVALENCE_SCHEMA",
    "FeatureFlagStore",
    "FlagStore",
    "CanaryController",
    "DimensionTolerance",
    "SHADOW_REPORT_SCHEMA",
    "compare_shadow_row",
    "evaluate_gate",
    "evaluate_shadow_reports",
    "normalize_effect_request",
]


if __name__ == "__main__":
    raise SystemExit(main())
