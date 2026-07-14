from agent.adapter_contract import AdapterContract

def test_adapter_contract_prefers_structured_operations_and_gates_external_effects():
    contract = AdapterContract("xlsx", ("read", "write"), "formula-and-render", ("openpyxl",))
    assert contract.to_dict()["fallback"] == "computer-use"
    assert contract.to_dict()["external_effects_require_approval"]
    assert len(contract.content_hash()) == 64
