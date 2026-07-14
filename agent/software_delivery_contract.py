"""Software-builder delivery evidence contract."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

SOFTWARE_DELIVERY_SCHEMA = "simplicio.software-delivery/v1"

@dataclass(frozen=True, slots=True)
class SoftwareDeliveryContract:
    goal_hash: str
    artifacts: tuple[str, ...]
    tests_receipt: str
    runtime_gate_receipt: str
    watcher_receipt: str

    def __post_init__(self) -> None:
        for name in ("goal_hash", "tests_receipt", "runtime_gate_receipt", "watcher_receipt"):
            value = str(getattr(self, name)).strip()
            if not value: raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        artifacts = tuple(sorted({str(item).strip() for item in self.artifacts}))
        if not artifacts or any(not item for item in artifacts): raise ValueError("artifacts must be non-empty")
        object.__setattr__(self, "artifacts", artifacts)

    @property
    def deliverable(self) -> bool:
        return bool(self.tests_receipt and self.runtime_gate_receipt and self.watcher_receipt)

    def to_dict(self):
        return {"schema": SOFTWARE_DELIVERY_SCHEMA, "goal_hash": self.goal_hash, "artifacts": list(self.artifacts),
                "tests_receipt": self.tests_receipt, "runtime_gate_receipt": self.runtime_gate_receipt,
                "watcher_receipt": self.watcher_receipt, "deliverable": self.deliverable}

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
