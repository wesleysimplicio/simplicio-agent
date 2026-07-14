"""Computer-use provider routing and post-effect verification contract."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

COMPUTER_USE_PROVIDER_SCHEMA = "simplicio.computer-use-provider/v1"

@dataclass(frozen=True, slots=True)
class ComputerUseProviderContract:
    provider: str
    capabilities: tuple[str, ...]
    health_probe: str
    effect_receipt: str
    structured_first: bool = True
    human_gate_required: bool = True

    def __post_init__(self) -> None:
        for name in ("provider", "health_probe", "effect_receipt"):
            value = str(getattr(self, name)).strip()
            if not value: raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        capabilities = tuple(sorted({str(item).strip() for item in self.capabilities}))
        if not capabilities or any(not item for item in capabilities): raise ValueError("capabilities must be non-empty")
        object.__setattr__(self, "capabilities", capabilities)
        if not self.structured_first or not self.human_gate_required:
            raise ValueError("computer-use safety defaults must be enabled")

    def to_dict(self):
        return {"schema": COMPUTER_USE_PROVIDER_SCHEMA, "provider": self.provider, "capabilities": list(self.capabilities),
                "health_probe": self.health_probe, "effect_receipt": self.effect_receipt,
                "structured_first": self.structured_first, "human_gate_required": self.human_gate_required}

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
