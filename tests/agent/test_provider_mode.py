"""Unit tests for agent.provider_mode (issue #64)."""

from __future__ import annotations

import pytest

from agent.provider_mode import (
    ProviderMode,
    CallContract,
    MCPInvocationOrigin,
    resolve_provider_mode,
    build_call_contract,
    gate_llm_call,
    should_bypass_llm,
)


class TestProviderMode:

    def test_standalone_is_not_mcp(self):
        assert ProviderMode.STANDALONE.value == "standalone"
        assert ProviderMode.STANDALONE.is_llm_allowed()
        assert ProviderMode.STANDALONE.is_standalone()
        assert not ProviderMode.STANDALONE.is_tool()
        assert not ProviderMode.STANDALONE.is_delegated()

    def test_tool_forbids_llm(self):
        assert ProviderMode.TOOL.value == "tool"
        assert not ProviderMode.TOOL.is_llm_allowed()
        assert ProviderMode.TOOL.is_tool()

    def test_delegated_allows_llm(self):
        assert ProviderMode.DELEGATED.value == "delegated"
        assert ProviderMode.DELEGATED.is_llm_allowed()
        assert ProviderMode.DELEGATED.is_delegated()


class TestResolveProviderMode:

    def test_non_mcp_is_standalone(self):
        class FakeOrigin:
            is_mcp = False
            has_provider_ref = False
            caller_label = "cli"
        mode = resolve_provider_mode(FakeOrigin())
        assert mode == ProviderMode.STANDALONE

    def test_mcp_without_ref_is_tool(self):
        origin = MCPInvocationOrigin(caller_label="claude-code")
        assert resolve_provider_mode(origin) == ProviderMode.TOOL

    def test_mcp_with_ref_is_delegated(self):
        origin = MCPInvocationOrigin(caller_label="claude-code", provider_ref="openai/gpt-4o")
        assert resolve_provider_mode(origin) == ProviderMode.DELEGATED

    def test_mcp_empty_ref_is_still_tool(self):
        origin = MCPInvocationOrigin(provider_ref="")
        assert resolve_provider_mode(origin) == ProviderMode.TOOL


class TestCallContract:

    def test_tool_mode_assertion_raises(self):
        contract = CallContract(mode=ProviderMode.TOOL)
        with pytest.raises(RuntimeError, match="tool mode forbids"):
            contract.assert_allowed()

    def test_delegated_without_ref_is_ok(self):
        contract = CallContract(mode=ProviderMode.DELEGATED, provider_ref=None)
        contract.assert_allowed()  # should not raise

    def test_delegated_with_ref_and_gate_allowed(self):
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="openai/gpt-4o",
            action_gate_result="allowed",
        )
        contract.assert_allowed()  # should not raise

    def test_delegated_with_ref_and_gate_denied_raises(self):
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="openai/gpt-4o",
            action_gate_result="denied",
        )
        with pytest.raises(RuntimeError, match="denied"):
            contract.assert_allowed()

    def test_with_gate_result_returns_new_contract(self):
        c1 = CallContract(mode=ProviderMode.DELEGATED, provider_ref="test")
        c2 = c1.with_gate_result("allowed")
        assert c2.action_gate_result == "allowed"
        assert c1.action_gate_result is None
        assert c1 is not c2

    def test_to_dict_redacts_when_flag_set(self):
        contract = CallContract(
            provider_ref="sk-abc123",
            mode=ProviderMode.DELEGATED,
            redacted=True,
        )
        d = contract.to_dict()
        assert d["provider_ref"] == "<redacted>"

    def test_to_dict_shows_ref_when_not_redacted(self):
        contract = CallContract(
            provider_ref="openai/gpt-4o",
            mode=ProviderMode.DELEGATED,
        )
        d = contract.to_dict()
        assert d["provider_ref"] == "openai/gpt-4o"


class TestBuildCallContract:

    def test_standalone_contract(self):
        class FakeOrigin:
            is_mcp = False
            has_provider_ref = False
            provider_ref = None
            caller_label = "cli-user"
        contract = build_call_contract(FakeOrigin())
        assert contract.mode == ProviderMode.STANDALONE
        assert contract.cost_attribution == "agent"

    def test_tool_contract(self):
        origin = MCPInvocationOrigin(caller_label="cursor")
        contract = build_call_contract(origin, session_id="sess-1")
        assert contract.mode == ProviderMode.TOOL
        assert contract.cost_attribution == "agent"
        assert contract.session_id == "sess-1"

    def test_delegated_contract(self):
        origin = MCPInvocationOrigin(
            caller_label="claude-code",
            provider_ref="openai/gpt-4o",
        )
        contract = build_call_contract(origin, session_id="sess-2")
        assert contract.mode == ProviderMode.DELEGATED
        assert contract.cost_attribution == "caller"
        assert contract.provider_ref == "openai/gpt-4o"

    def test_delegated_redacted(self):
        origin = MCPInvocationOrigin(
            caller_label="claude-code",
            provider_ref="sk-abc",
        )
        contract = build_call_contract(origin, redacted=True)
        assert contract.provider_ref is None
        assert contract.redacted


class TestGateLLMCall:

    def test_tool_mode_raises(self):
        contract = CallContract(mode=ProviderMode.TOOL)
        with pytest.raises(RuntimeError):
            gate_llm_call(contract)

    def test_standalone_no_gate_needed(self):
        contract = CallContract(mode=ProviderMode.STANDALONE)
        result = gate_llm_call(contract)
        assert result is contract

    def test_delegated_no_ref_passes_through(self):
        contract = CallContract(mode=ProviderMode.DELEGATED, provider_ref=None)
        result = gate_llm_call(contract)
        assert result is contract

    def test_gate_allows(self):
        class FakeGate:
            def classify(self, **kw):
                return {"allowed": True}
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="oai/gpt4",
        )
        result = gate_llm_call(contract, action_gate=FakeGate())
        assert result.action_gate_result == "allowed"
        assert result.provider_ref == "oai/gpt4"

    def test_gate_denies_falls_back_to_local(self):
        class FakeGate:
            def classify(self, **kw):
                return {"allowed": False}
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="oai/gpt4",
        )
        result = gate_llm_call(contract, action_gate=FakeGate())
        assert result.provider_ref is None
        assert result.cost_attribution == "agent"
        assert result.action_gate_result == "denied"

    def test_no_gate_available_denies_and_falls_back(self):
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="oai/gpt4",
        )
        result = gate_llm_call(contract, action_gate=None)
        assert result.provider_ref is None
        assert result.action_gate_result == "denied"

    def test_gate_exception_falls_back(self):
        class BrokenGate:
            def classify(self, **kw):
                raise ValueError("gate down")
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="oai/gpt4",
        )
        result = gate_llm_call(contract, action_gate=BrokenGate())
        assert result.provider_ref is None
        assert result.action_gate_result == "denied"

    def test_no_fallback_raises(self):
        class FakeGate:
            def classify(self, **kw):
                return {"allowed": False}
        contract = CallContract(
            mode=ProviderMode.DELEGATED,
            provider_ref="oai/gpt4",
        )
        with pytest.raises(RuntimeError, match="denied"):
            gate_llm_call(contract, action_gate=FakeGate(), auto_fallback_to_local=False)


class TestShouldBypassLLM:

    def test_tool_bypasses(self):
        assert should_bypass_llm(CallContract(mode=ProviderMode.TOOL))

    def test_standalone_does_not_bypass(self):
        assert not should_bypass_llm(CallContract(mode=ProviderMode.STANDALONE))

    def test_delegated_does_not_bypass(self):
        assert not should_bypass_llm(CallContract(mode=ProviderMode.DELEGATED))


class TestMCPInvocationOrigin:

    def test_default_construction(self):
        o = MCPInvocationOrigin()
        assert o.is_mcp
        assert not o.has_provider_ref
        assert o.provider_ref is None
        assert o.caller_label == "mcp-unknown"

    def test_with_provider_ref(self):
        o = MCPInvocationOrigin(provider_ref="anthropic/claude")
        assert o.has_provider_ref
        assert o.provider_ref == "anthropic/claude"

    def test_empty_provider_ref_is_not_considered_set(self):
        o = MCPInvocationOrigin(provider_ref="")
        assert not o.has_provider_ref

    def test_caller_label(self):
        o = MCPInvocationOrigin(caller_label="my-custom-caller")
        assert o.caller_label == "my-custom-caller"