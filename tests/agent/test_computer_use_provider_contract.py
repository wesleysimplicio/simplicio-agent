from agent.computer_use_provider_contract import ComputerUseProviderContract

def test_computer_use_provider_requires_health_and_effect_receipts():
    contract = ComputerUseProviderContract("cua", ("capture", "click", "type"), "cua.health", "effect.receipt")
    assert contract.to_dict()["human_gate_required"]
    assert len(contract.content_hash()) == 64
