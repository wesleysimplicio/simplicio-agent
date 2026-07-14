import pytest

from agent.capability_inventory import (
    CapabilityDisposition,
    CapabilityInventory,
    CapabilityRecord,
)


def test_inventory_requires_receipt_and_is_canonical():
    record = CapabilityRecord(
        name="browser",
        disposition=CapabilityDisposition.WRAP,
        entrypoint="agent.browser",
        owner="agent",
        health_probe="browser.health",
        verifier="dom.receipt",
        risk_class="read",
        evidence="test:browser-smoke",
    )
    inventory = CapabilityInventory((record,))
    assert inventory.to_dict()["schema"] == "simplicio.capability-inventory/v1"
    assert len(inventory.content_hash()) == 64


def test_repair_capability_without_reason_is_fail_closed():
    with pytest.raises(ValueError, match="reason_code"):
        CapabilityRecord(
            "runtime", CapabilityDisposition.REPAIR, "tools.runtime", "runtime",
            "runtime.health", "handshake", "process_execution", "blocked",
        )
