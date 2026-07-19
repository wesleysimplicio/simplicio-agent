import json
import re
from pathlib import Path

import yaml

from tools.locale_contract import (
    CURRENT_CONTRACT_VERSION,
    INVENTORY_SCHEMA,
    MATRIX_SCHEMA,
    PARITY_SCHEMA,
    RECEIPT_SCHEMA,
    build_locale_inventory,
    build_locale_receipt,
    build_required_locale_parity,
    build_locale_matrix,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "locales"
REPO_LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"
GLOSSARY_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "product-language-glossary.yaml"
)


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

    required = {
        entry["requested_locale"]: entry
        for entry in inventory["required_product_locales"]
    }

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


def test_all_shipped_locales_have_key_and_placeholder_parity():
    matrix = build_locale_matrix(REPO_LOCALES_DIR)

    assert matrix["schema"] == MATRIX_SCHEMA
    assert matrix["ok"] is True
    assert len(matrix["catalogs"]) == 16
    assert {catalog["locale"] for catalog in matrix["catalogs"]} == {
        path.stem for path in REPO_LOCALES_DIR.glob("*.yaml")
    }
    for catalog in matrix["catalogs"]:
        assert catalog["missing_keys"] == []
        assert catalog["extra_keys"] == []
        assert catalog["placeholder_mismatches"] == []
        assert catalog["branding_classification"] == "simplicio_only"


def test_branding_classification_distinguishes_current_mixed_and_unbranded_catalogs():
    inventory = build_locale_inventory(FIXTURE_DIR)
    catalogs = {entry["locale"]: entry for entry in inventory["catalogs"]}

    assert catalogs["en"]["branding_classification"] == "simplicio_only"
    assert catalogs["pt"]["branding_classification"] == "mixed"
    assert catalogs["fr"]["branding_classification"] == "unbranded"


def test_repository_help_headers_use_canonical_product_name():
    for path in sorted(REPO_LOCALES_DIR.glob("*.yaml")):
        catalog = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        header = catalog["gateway"]["help"]["header"]
        assert "Simplicio Agent" in header, path.name
        assert "Hermes" not in header, path.name


def test_repository_catalog_values_use_only_canonical_product_identity():
    inventory = build_locale_inventory(REPO_LOCALES_DIR)

    for catalog in inventory["catalogs"]:
        assert catalog["branding_classification"] == "simplicio_only", catalog[
            "catalog_file"
        ]


def test_contextual_legacy_scan_allows_only_the_stable_locale_key():
    legacy = re.compile(r"hermes", re.IGNORECASE)
    stable_key = "hermes_cmd_not_found"

    for path in sorted(REPO_LOCALES_DIR.glob("*.yaml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        key_lines = [line for line in lines if stable_key in line]
        assert len(key_lines) == 1, path.name

        for line_number, line in enumerate(lines, start=1):
            if not legacy.search(line):
                continue
            assert re.match(rf"^\s*{stable_key}\s*:", line), (
                f"{path.name}:{line_number}: non-contextual legacy identity: {line}"
            )
            public_value = line.split(":", 1)[1]
            assert not legacy.search(public_value), (
                f"{path.name}:{line_number}: legacy identity leaked into public copy"
            )


def test_machine_readable_glossary_pins_product_and_technical_terms():
    glossary = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))

    assert glossary["schema"] == "simplicio.agent.product-language/v1"
    agent_term = glossary["product_names"]["agent"]
    assert agent_term["canonical"] == "Simplicio Agent"
    assert agent_term["kind"] == "proper_noun"
    assert agent_term["translate"] is False
    assert glossary["product_names"]["runtime"]["canonical"] == "Simplicio Runtime"
    assert glossary["product_names"]["runtime"]["executable"] == "simplicio"
    assert glossary["product_names"]["cli"]["canonical"] == "simplicio-agent"
    for product_name in glossary["product_names"].values():
        assert product_name["translate"] is False
        assert product_name["translator_comment"]

    required_terms = {"run", "checkpoint", "receipt", "capability", "awareness"}
    assert required_terms <= set(glossary["terms"])
    for term in required_terms:
        assert glossary["terms"][term]["meaning"]
        assert glossary["terms"][term]["translator_comment"]
    assert glossary["legacy_identity"]["public_copy"] == "forbidden"
    assert set(glossary["legacy_identity"]["allowed_contexts"]) == {
        "credit",
        "legacy_alias",
        "migration",
    }
    assert glossary["legacy_identity"]["stable_locale_keys"] == [
        "gateway.update.hermes_cmd_not_found"
    ]
