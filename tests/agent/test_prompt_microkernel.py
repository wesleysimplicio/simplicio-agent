"""Focused contracts for the #318 lazy prompt microkernel."""

from agent.prompt_microkernel import (
    FIXED_SCHEMA_MAX_BYTES,
    PRIMITIVES,
    CapabilityBroker,
    build_capsule,
    pin_existing_capabilities,
)


def test_five_primitives_are_lazy_and_schema_is_bounded():
    capsule = build_capsule(context_ids=["b", "a"], delta_ids=["d1"])
    assert capsule.primitives == PRIMITIVES
    assert capsule.schema_bytes < FIXED_SCHEMA_MAX_BYTES
    assert capsule.prompt_tokens < 2_000
    assert capsule.cache_stable is True
    assert (
        capsule.prefix_sha256
        == build_capsule(context_ids=["a", "b"], delta_ids=["d1"]).prefix_sha256
    )


def test_capability_parity_receipt_reports_exact_current_set():
    capabilities = [
        {"name": "read_file", "description": "read"},
        {"name": "patch", "description": "patch"},
    ]
    receipt = CapabilityBroker(capabilities).parity_receipt(["patch", "read_file"])
    assert receipt.equivalent
    assert receipt.missing == receipt.extra == ()
    assert receipt.schema_bytes > 0
    assert receipt.cache_stable is True


def test_existing_bundle_pin_preserves_all_schemas():
    tools = [
        {"type": "function", "function": {"name": "read_file", "description": "read"}},
        {"type": "function", "function": {"name": "patch", "description": "patch"}},
    ]
    pinned = pin_existing_capabilities(tools, task="patch a file")
    assert {item["function"]["name"] for item in pinned} == {"read_file", "patch"}
    assert all(item["type"] == "function" for item in pinned)
