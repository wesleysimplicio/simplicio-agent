from agent.software_delivery_contract import SoftwareDeliveryContract

def test_software_delivery_requires_tests_gate_and_watcher_receipts():
    contract = SoftwareDeliveryContract("goal:1", ("app.zip", "tests.log"), "tests:1", "gate:1", "watcher:1")
    assert contract.deliverable
    assert len(contract.content_hash()) == 64
