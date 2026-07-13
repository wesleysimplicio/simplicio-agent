import json
from pathlib import Path

import pytest

from tools.machine_contracts import (
    CURRENT_CONTRACT_VERSION,
    MATRIX_SCHEMA,
    PRODUCT_SCHEMA,
    ReceiptMetadata,
    build_machine_contract,
    compatibility_matrix,
    compatibility_report,
    compatibility_row,
    make_component_identity,
    upcast_legacy_contract,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "machine-contracts"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_build_machine_contract_separates_agent_and_runtime_identities():
    contract = build_machine_contract(
        product_version="3.40.0",
        agent_version="3.40.1",
        runtime_version="3.40.9",
        agent_features=("chat_ux", "autonomy"),
        runtime_features=("action_gate", "checkpoint"),
    ).to_dict()

    assert contract["schema"] == PRODUCT_SCHEMA
    assert contract["contract_version"] == CURRENT_CONTRACT_VERSION
    assert contract["product"]["product"] == "Simplicio Agent"
    assert contract["agent"]["role"] == "agent"
    assert contract["agent"]["boundary"] == "orchestration"
    assert contract["runtime"]["role"] == "runtime"
    assert contract["runtime"]["boundary"] == "deterministic_kernel"
    assert contract["agent"]["capability_envelope"]["features"] == ["chat_ux", "autonomy"]
    assert contract["runtime"]["capability_envelope"]["features"] == ["action_gate", "checkpoint"]


def test_capability_envelope_declares_schema_producer_window():
    component = make_component_identity(
        "simplicio-runtime",
        "3.40.9",
        role="runtime",
        boundary="deterministic_kernel",
        produced_version=2,
        min_consumer_version=1,
        max_consumer_version=3,
        features=("mechanical_edit",),
    ).to_dict()

    envelope = component["capability_envelope"]
    assert envelope["producer"] == "simplicio-runtime"
    assert envelope["schema_family"] == "machine-contracts"
    assert envelope["produced_version"] == 2
    assert envelope["min_consumer_version"] == 1
    assert envelope["max_consumer_version"] == 3
    assert envelope["features"] == ["mechanical_edit"]


def test_legacy_upcaster_normalizes_legacy_fixture():
    legacy = _load_fixture("legacy-contract.json")

    upcast = upcast_legacy_contract(legacy)

    assert upcast["schema"] == PRODUCT_SCHEMA
    assert upcast["contract_version"] == CURRENT_CONTRACT_VERSION
    assert upcast["legacy_source_schema"] == "machine_contract"
    assert upcast["legacy_adapter"]["upcast_to"] == PRODUCT_SCHEMA
    assert upcast["agent"]["version"] == "3.39.0"
    assert upcast["runtime"]["version"] == "3.39.4"
    assert upcast["agent"]["capability_envelope"]["features"] == ["chat_ux", "skills"]


def test_receipt_metadata_redacts_sensitive_fields():
    metadata = ReceiptMetadata(
        request_id="req-123",
        transport="cli",
        redaction_applied=False,
        actor="doctor",
        path="C:/Users/example/project",
        environment="prod",
        raw_metadata={
            "cwd_path": "C:/Users/example/project",
            "api_key": "secret",
            "status": "ok",
        },
    )

    redacted = metadata.redacted()

    assert redacted["schema"] == "machine-contracts/receipt-metadata/v1"
    assert redacted["path"] == "[redacted]"
    assert redacted["environment"] == "[redacted]"
    assert redacted["raw_metadata"]["cwd_path"] == "[redacted]"
    assert redacted["raw_metadata"]["api_key"] == "[redacted]"
    assert redacted["raw_metadata"]["status"] == "ok"
    assert redacted["redaction_applied"] is True


def test_compatibility_report_accepts_matching_major_and_schema_window():
    agent = make_component_identity(
        "simplicio-agent",
        "3.40.1",
        role="agent",
        boundary="orchestration",
        produced_version=2,
        min_consumer_version=1,
        max_consumer_version=2,
    )
    runtime = make_component_identity(
        "simplicio-runtime",
        "3.40.9",
        role="runtime",
        boundary="deterministic_kernel",
        produced_version=2,
        min_consumer_version=1,
        max_consumer_version=2,
    )

    report = compatibility_report(agent=agent, runtime=runtime)

    assert report["schema"] == MATRIX_SCHEMA
    assert report["compatible"] is True
    assert report["reasons"] == ["compatible"]


def test_compatibility_report_flags_major_mismatch():
    agent = make_component_identity(
        "simplicio-agent",
        "3.40.1",
        role="agent",
        boundary="orchestration",
    )
    runtime = make_component_identity(
        "simplicio-runtime",
        "4.0.0",
        role="runtime",
        boundary="deterministic_kernel",
    )

    report = compatibility_report(agent=agent, runtime=runtime)

    assert report["compatible"] is False
    assert "major_version_mismatch" in report["reasons"]


def test_compatibility_matrix_helpers_return_versioned_rows():
    matrix = compatibility_matrix(
        [
            compatibility_row(
                agent_version="3.40.x",
                runtime_version="3.40.x",
                expected="compatible",
            ),
            {
                "agent_version": "3.40.x",
                "runtime_version": "4.0.x",
                "expected": "major_version_mismatch",
            },
        ]
    )

    assert matrix["schema"] == MATRIX_SCHEMA
    assert matrix["rows"] == [
        {
            "agent_version": "3.40.x",
            "runtime_version": "3.40.x",
            "expected": "compatible",
        },
        {
            "agent_version": "3.40.x",
            "runtime_version": "4.0.x",
            "expected": "major_version_mismatch",
        },
    ]


def test_current_fixture_matches_current_schema():
    current = _load_fixture("current-contract.json")

    assert current["schema"] == PRODUCT_SCHEMA
    assert current["contract_version"] == CURRENT_CONTRACT_VERSION
    assert current["compatibility"]["compatible"] is True


def test_upcaster_rejects_unknown_schema():
    with pytest.raises(ValueError, match="unsupported machine contract schema"):
        upcast_legacy_contract({"schema": "machine-contracts/product/v999"})
