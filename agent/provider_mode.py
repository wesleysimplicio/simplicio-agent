"""Provider-mode contract -- 3 modes of operation (issue #64).

Defines the explicit contract for which LLM provider the agent uses in each
invocation context. Every call_llm entry point consults the resolved mode
to decide whether a call is allowed, which provider ladder to use, and how
to attribute cost.
"""

from __future__ import annotations
import enum
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

class ProviderMode(enum.Enum):
    """The three provider-resolution modes."""
    STANDALONE = "standalone"
    TOOL = "tool"
    DELEGATED = "delegated"

    def __str__(self) -> str:
        return self.value
    def is_llm_allowed(self) -> bool:
        return self != ProviderMode.TOOL
    def is_standalone(self) -> bool:
        return self == ProviderMode.STANDALONE
    def is_tool(self) -> bool:
        return self == ProviderMode.TOOL
    def is_delegated(self) -> bool:
        return self == ProviderMode.DELEGATED

@dataclass(frozen=True)
class CallContract:
    """Immutable contract governing a single LLM call attempt."""
    mode: ProviderMode = ProviderMode.STANDALONE
    provider_ref: Optional[str] = None
    caller_label: str = "unknown"
    session_id: str = "unknown"
    cost_attribution: str = "agent"
    action_gate_result: Optional[str] = None
    redacted: bool = False

    def with_gate_result(self, result: str) -> "CallContract":
        return CallContract(
            mode=self.mode, provider_ref=self.provider_ref,
            caller_label=self.caller_label, session_id=self.session_id,
            cost_attribution=self.cost_attribution,
            action_gate_result=result, redacted=self.redacted,
        )

    def assert_allowed(self) -> None:
        if self.mode == ProviderMode.TOOL:
            raise RuntimeError("LLM call denied by mode=" + self.mode.value + ": tool mode forbids internal LLM calls")
        if self.provider_ref and self.action_gate_result != "allowed":
            s = self.action_gate_result or "unclassified"
            raise RuntimeError("LLM call denied: provider_ref=" + repr(self.provider_ref) + " gate_result=" + repr(s))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "provider_ref": "<redacted>" if self.redacted else self.provider_ref,
            "caller_label": self.caller_label,
            "session_id": self.session_id,
            "cost_attribution": self.cost_attribution,
            "action_gate_result": self.action_gate_result,
        }

class InvocationOrigin(Protocol):
    @property
    def is_mcp(self) -> bool: ...
    @property
    def has_provider_ref(self) -> bool: ...
    @property
    def provider_ref(self) -> Optional[str]: ...
    @property
    def caller_label(self) -> str: ...

class MCPInvocationOrigin:
    """Invocation origin for an MCP request."""
    def __init__(self, *, caller_label="mcp-unknown", provider_ref=None, session_id=""):
        self._caller_label = caller_label
        self._provider_ref = provider_ref
        self._session_id = session_id
    @property
    def is_mcp(self) -> bool:
        return True
    @property
    def has_provider_ref(self) -> bool:
        return self._provider_ref is not None and self._provider_ref.strip() != ""
    @property
    def provider_ref(self) -> Optional[str]:
        return self._provider_ref
    @property
    def caller_label(self) -> str:
        return self._caller_label

def resolve_provider_mode(origin: InvocationOrigin) -> ProviderMode:
    if not origin.is_mcp:
        return ProviderMode.STANDALONE
    if origin.has_provider_ref:
        return ProviderMode.DELEGATED
    return ProviderMode.TOOL

def build_call_contract(origin: InvocationOrigin, *, session_id="unknown", redacted=False) -> CallContract:
    mode = resolve_provider_mode(origin)
    cost_attr = "caller" if origin.has_provider_ref else "agent"
    return CallContract(
        mode=mode,
        provider_ref=origin.provider_ref if not redacted else None,
        caller_label=origin.caller_label,
        session_id=session_id,
        cost_attribution=cost_attr,
        action_gate_result=None,
        redacted=redacted,
    )

def gate_llm_call(contract: CallContract, *, action_gate: Any = None, auto_fallback_to_local: bool = True) -> CallContract:
    if contract.mode == ProviderMode.TOOL:
        contract.assert_allowed()
    if not contract.provider_ref:
        return contract
    if action_gate is not None and hasattr(action_gate, "classify"):
        try:
            result = action_gate.classify(
                resource_type="llm_provider",
                resource_id=contract.provider_ref,
                context={"session_id": contract.session_id, "caller": contract.caller_label},
            )
            gate_status = "allowed" if result.get("allowed", False) else "denied"
        except Exception as exc:
            logger.warning("Action Gate classify failed: %s", exc)
            gate_status = "denied"
    else:
        logger.warning("No Action Gate for provider_ref=%r. Denying.", contract.provider_ref)
        gate_status = "denied"
    if gate_status == "allowed":
        return contract.with_gate_result("allowed")
    if auto_fallback_to_local:
        logger.info("Provider ref %r denied. Falling back to local ladder.", contract.provider_ref)
        return CallContract(
            mode=ProviderMode.DELEGATED, provider_ref=None,
            caller_label=contract.caller_label, session_id=contract.session_id,
            cost_attribution="agent", action_gate_result=gate_status,
            redacted=contract.redacted,
        )
    denied = contract.with_gate_result(gate_status)
    denied.assert_allowed()
    return denied

def should_bypass_llm(contract: CallContract) -> bool:
    return not contract.mode.is_llm_allowed()

__all__ = [
    "ProviderMode", "CallContract",
    "InvocationOrigin", "MCPInvocationOrigin",
    "resolve_provider_mode", "build_call_contract",
    "gate_llm_call", "should_bypass_llm",
]