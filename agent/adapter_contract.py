"""Common structured adapter contract for document/app/mobile surfaces."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

ADAPTER_CONTRACT_SCHEMA = "simplicio.adapter-contract/v1"

@dataclass(frozen=True, slots=True)
class AdapterContract:
    name: str
    operations: tuple[str, ...]
    verifier: str
    dependencies: tuple[str, ...] = ()
    fallback: str = "computer-use"
    external_effects_require_approval: bool = True

    def __post_init__(self) -> None:
        for name in ("name", "verifier", "fallback"):
            value = str(getattr(self, name)).strip()
            if not value: raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        for name in ("operations", "dependencies"):
            values = tuple(sorted({str(item).strip() for item in getattr(self, name)}))
            if not values or any(not item for item in values): raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, values)
        if not isinstance(self.external_effects_require_approval, bool):
            raise TypeError("external_effects_require_approval must be boolean")

    def to_dict(self):
        return {"schema": ADAPTER_CONTRACT_SCHEMA, "name": self.name, "operations": list(self.operations),
                "verifier": self.verifier, "dependencies": list(self.dependencies), "fallback": self.fallback,
                "external_effects_require_approval": self.external_effects_require_approval}

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
