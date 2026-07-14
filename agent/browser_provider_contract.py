"""Browser provider routing and safety contract."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass

BROWSER_PROVIDER_SCHEMA = "simplicio.browser-provider/v1"

@dataclass(frozen=True, slots=True)
class BrowserProviderContract:
    provider: str
    capabilities: tuple[str, ...]
    structured_first: bool = True
    secrets_handle_only: bool = True
    human_gate_risks: tuple[str, ...] = ("captcha", "2fa", "payment", "prompt_injection")

    def __post_init__(self) -> None:
        if not str(self.provider).strip(): raise ValueError("provider must be non-empty")
        capabilities = tuple(sorted({str(item).strip() for item in self.capabilities}))
        if not capabilities or any(not item for item in capabilities): raise ValueError("capabilities must be non-empty")
        object.__setattr__(self, "provider", str(self.provider).strip())
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "human_gate_risks", tuple(sorted(set(self.human_gate_risks))))
        if not self.structured_first or not self.secrets_handle_only: raise ValueError("browser safety defaults must be enabled")

    def to_dict(self):
        return {"schema": BROWSER_PROVIDER_SCHEMA, "provider": self.provider, "capabilities": list(self.capabilities),
                "structured_first": self.structured_first, "secrets_handle_only": self.secrets_handle_only,
                "human_gate_risks": list(self.human_gate_risks)}

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
