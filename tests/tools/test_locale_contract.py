import json
from pathlib import Path

from tools.locale_contract import (
    CURRENT_CONTRACT_VERSION,
    INVENTORY_SCHEMA,
    PARITY_SCHEMA,
    RECEIPT_SCHEMA,
    build_locale_inventory,
    build_locale_receipt,
    build_required_locale_parity,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "locales"
REPO_LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_fixture_inventory_matches_expected_snapshot():
    inventory = build_locale_inventory(FIXTURE_DIR)

    assert inventory["schema"] == INVENTORY_SCHEMA
    assert inventory["contract_version"] == CURRENT_CONTRACT_VERSION
    assert inventory == _load_json("expected-inventory.json")


def test_fixture_receipt_matches_expected_snapshot():
    receipt = build_locale_receipt(FIXTURE_DIR)

    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["contract_version"] == CURRENT_CONTRACT_VERSION
    assert receipt == _load_json("expected-receipt.json")


def test_inventory_is_deterministic():
    first = build_locale_inventory(FIXTURE_DIR)
    second = build_locale_inventory(FIXTURE_DIR)

    assert first == second
    assert first["deterministic_order"] == ["en", "fr", "pt"]


def test_required_product_locales_use_alias_fallback_and_key_parity_on_repo_catalogs():
    inventory = build_locale_inventory(REPO_LOCALES_DIR)
    parity = build_required_locale_parity(REPO_LOCALES_DIR)

    required = {entry["requested_locale"]: entry for entry in inventory["required_product_locales"]}

    assert required["en-US"]["canonical_locale"] == "en"
    assert required["en-US"]["fallback_classification"] == "alias_fallback"
    assert required["pt-BR"]["canonical_locale"] == "pt"
    assert required["pt-BR"]["fallback_classification"] == "alias_fallback"
    assert parity["schema"] == PARITY_SCHEMA
    assert parity["baseline_locale"] == "en-US"
    assert parity["target_locale"] == "pt-BR"
    assert parity["key_parity"] is True
    assert parity["missing_keys"] == []
    assert parity["extra_keys"] == []


def test_branding_classification_distinguishes_current_mixed_and_unbranded_catalogs():
    inventory = build_locale_inventory(FIXTURE_DIR)
    catalogs = {entry["locale"]: entry for entry in inventory["catalogs"]}

    assert catalogs["en"]["branding_classification"] == "simplicio_only"
    assert catalogs["pt"]["branding_classification"] == "mixed"
    assert catalogs["fr"]["branding_classification"] == "unbranded"
