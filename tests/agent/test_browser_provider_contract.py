from agent.browser_provider_contract import BrowserProviderContract

def test_browser_provider_defaults_to_structured_and_handle_safe():
    contract = BrowserProviderContract("playwright", ("navigate", "snapshot", "download"))
    assert contract.to_dict()["structured_first"]
    assert "prompt_injection" in contract.to_dict()["human_gate_risks"]
    assert len(contract.content_hash()) == 64
