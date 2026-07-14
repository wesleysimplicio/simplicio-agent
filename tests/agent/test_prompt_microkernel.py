"""Focused contracts for the #318 lazy prompt microkernel."""

import json
from pathlib import Path

from agent.prompt_microkernel import (
    FIXED_SCHEMA_MAX_BYTES,
    PRIMITIVE_BOUNDARIES,
    PRIMITIVES,
    CapabilityBroker,
    build_capsule,
    pin_existing_capabilities,
)
import pytest


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


def test_ids_and_deltas_are_canonical_and_receipt_is_deterministic():
    first = build_capsule(
        context_ids=["ctx:b", "ctx:a", "ctx:a"],
        delta_ids=["delta:2", "delta:1"],
    )
    second = build_capsule(
        context_ids=["ctx:a", "ctx:b"],
        delta_ids=["delta:1", "delta:2"],
    )
    assert first == second
    assert first.receipt.to_dict() == second.receipt.to_dict()
    assert first.schema_sha256
    assert first.receipt.to_dict()["schema_version"].endswith("/v1")


def test_representative_receipt_fixture_matches_local_contract():
    fixture = json.loads(
        (
            Path(__file__).parents[1]
            / "fixtures"
            / "native"
            / "prompt_microkernel_receipt.json"
        ).read_text()
    )
    capsule = build_capsule(context_ids=["ctx:alpha"], delta_ids=["delta:2", "delta:1"])
    assert capsule.receipt.to_dict() == {
        key: fixture[key]
        for key in (
            "schema_version",
            "context_ids",
            "delta_ids",
            "schema_bytes",
            "schema_sha256",
            "prefix_sha256",
            "cache_stable",
        )
    }
    assert list(capsule.primitives) == fixture["primitives"]


@pytest.mark.parametrize("field", ["context_ids", "delta_ids"])
def test_ids_reject_whitespace_and_non_strings(field):
    kwargs = {field: ["not stable"]}
    with pytest.raises(ValueError, match=field):
        build_capsule(**kwargs)

    kwargs = {field: [1]}
    with pytest.raises(ValueError, match=field):
        build_capsule(**kwargs)


def test_broker_expands_wrapped_existing_schema_on_demand_with_receipt():
    broker = CapabilityBroker([
        {
            "type": "function",
            "function": {"name": "act", "description": "existing"},
        }
    ])
    schema, receipt = broker.expand_with_receipt("act")
    assert schema["function"]["name"] == "act"
    assert receipt.boundary == PRIMITIVE_BOUNDARIES["act"]
    assert receipt == broker.expand_with_receipt("act")[1]
    schema["function"]["description"] = "caller mutation"
    assert broker.expand("act")["function"]["description"] == "existing"


def test_parity_receipt_is_explicit_for_missing_and_extra_capabilities():
    receipt = CapabilityBroker([{"name": "inspect"}, {"name": "extra"}]).parity_receipt(
        PRIMITIVES
    )
    assert receipt.missing == ("act", "decide", "recall", "verify")
    assert receipt.extra == ("extra",)
    assert receipt.equivalent is False
    assert receipt.to_dict() == receipt.to_dict()
