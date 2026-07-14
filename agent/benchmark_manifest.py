"""Versioned task manifests for reproducible Universal Operator benchmarks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


BENCHMARK_MANIFEST_SCHEMA = "simplicio.benchmark-task/v1"


@dataclass(frozen=True, slots=True)
class BenchmarkTaskManifest:
    task_id: str
    domain: str
    setup: str
    goal: str
    constraints: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    verifier: str
    timeout_s: int
    risk_mode: str

    def __post_init__(self) -> None:
        for name in ("task_id", "domain", "setup", "goal", "verifier", "risk_mode"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        for name in ("constraints", "expected_artifacts"):
            values = tuple(sorted({str(item).strip() for item in getattr(self, name)}))
            if any(not item for item in values):
                raise ValueError(f"{name} must contain non-empty values")
            object.__setattr__(self, name, values)
        if not isinstance(self.timeout_s, int) or isinstance(self.timeout_s, bool) or self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BENCHMARK_MANIFEST_SCHEMA,
            "task_id": self.task_id,
            "domain": self.domain,
            "setup": self.setup,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "expected_artifacts": list(self.expected_artifacts),
            "verifier": self.verifier,
            "timeout_s": self.timeout_s,
            "risk_mode": self.risk_mode,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["BENCHMARK_MANIFEST_SCHEMA", "BenchmarkTaskManifest"]
