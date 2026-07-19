"""Deterministic locale inventory and parity receipts for product languages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml

from agent.i18n import DEFAULT_LANGUAGE, _normalize_lang

INVENTORY_SCHEMA = "locale-contracts/inventory/v1"
PARITY_SCHEMA = "locale-contracts/key-parity/v1"
MATRIX_SCHEMA = "locale-contracts/matrix/v1"
RECEIPT_SCHEMA = "locale-contracts/receipt/v1"
CURRENT_CONTRACT_VERSION = 1
REQUIRED_PRODUCT_LOCALES = ("en-US", "pt-BR")

_LEGACY_BRAND = "Hermes"
_CURRENT_BRAND = "Simplicio Agent"
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([^{}]+)\}(?!\})")


def _flatten(node: Any, prefix: str = "", out: dict[str, str] | None = None) -> dict[str, str]:
    result = out if out is not None else {}
    if isinstance(node, dict):
        for key, value in node.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            _flatten(value, child_key, result)
    elif isinstance(node, str):
        result[prefix] = node
    return result


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _classify_branding(values: list[str]) -> str:
    has_legacy = any(_LEGACY_BRAND in value for value in values)
    has_current = any(_CURRENT_BRAND in value for value in values)
    if has_legacy and has_current:
        return "mixed"
    if has_legacy:
        return "legacy_hermes_only"
    if has_current:
        return "simplicio_only"
    return "unbranded"


def _load_catalog(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return _flatten(raw)


@dataclass(frozen=True)
class LocaleCatalog:
    locale: str
    catalog_file: str
    key_count: int
    key_digest: str
    branding_classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequestedLocale:
    requested_locale: str
    canonical_locale: str
    catalog_file: str
    fallback_classification: str
    branding_classification: str
    key_count: int
    key_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _catalog_files(locales_dir: Path) -> list[Path]:
    return sorted(locales_dir.glob("*.yaml"), key=lambda path: path.stem)


def _build_catalogs(locales_dir: Path) -> tuple[list[LocaleCatalog], dict[str, dict[str, str]]]:
    catalogs: list[LocaleCatalog] = []
    flattened: dict[str, dict[str, str]] = {}
    for path in _catalog_files(locales_dir):
        flat = _load_catalog(path)
        flattened[path.stem] = flat
        catalogs.append(
            LocaleCatalog(
                locale=path.stem,
                catalog_file=path.name,
                key_count=len(flat),
                key_digest=_sha256_text(_canonical_json(flat)),
                branding_classification=_classify_branding(list(flat.values())),
            )
        )
    return catalogs, flattened


def _resolve_requested_locale(
    requested_locale: str,
    *,
    catalogs: dict[str, dict[str, str]],
) -> RequestedLocale:
    requested_key = requested_locale.strip().lower()
    fallback_classification = "direct_catalog"
    canonical_locale = requested_key
    if requested_key not in catalogs:
        canonical_locale = _normalize_lang(requested_locale)
        fallback_classification = (
            "alias_fallback" if canonical_locale in catalogs else "default_fallback"
        )
    if canonical_locale not in catalogs:
        canonical_locale = DEFAULT_LANGUAGE
    flat = catalogs[canonical_locale]
    return RequestedLocale(
        requested_locale=requested_locale,
        canonical_locale=canonical_locale,
        catalog_file=f"{canonical_locale}.yaml",
        fallback_classification=fallback_classification,
        branding_classification=_classify_branding(list(flat.values())),
        key_count=len(flat),
        key_digest=_sha256_text(_canonical_json(flat)),
    )


def build_locale_inventory(
    locales_dir: Path,
    *,
    required_product_locales: tuple[str, ...] = REQUIRED_PRODUCT_LOCALES,
) -> dict[str, Any]:
    catalogs, flattened = _build_catalogs(locales_dir)
    required_locales = [
        _resolve_requested_locale(locale, catalogs=flattened).to_dict()
        for locale in required_product_locales
    ]
    return {
        "schema": INVENTORY_SCHEMA,
        "contract_version": CURRENT_CONTRACT_VERSION,
        "catalogs": [catalog.to_dict() for catalog in catalogs],
        "required_product_locales": required_locales,
        "deterministic_order": [catalog.locale for catalog in catalogs],
    }


def build_required_locale_parity(
    locales_dir: Path,
    *,
    baseline_locale: str = "en-US",
    target_locale: str = "pt-BR",
) -> dict[str, Any]:
    _, flattened = _build_catalogs(locales_dir)
    baseline = _resolve_requested_locale(baseline_locale, catalogs=flattened)
    target = _resolve_requested_locale(target_locale, catalogs=flattened)
    baseline_keys = set(flattened[baseline.canonical_locale])
    target_keys = set(flattened[target.canonical_locale])
    missing_keys = sorted(baseline_keys - target_keys)
    extra_keys = sorted(target_keys - baseline_keys)
    return {
        "schema": PARITY_SCHEMA,
        "contract_version": CURRENT_CONTRACT_VERSION,
        "baseline_locale": baseline.requested_locale,
        "baseline_canonical_locale": baseline.canonical_locale,
        "target_locale": target.requested_locale,
        "target_canonical_locale": target.canonical_locale,
        "key_parity": not missing_keys and not extra_keys,
        "missing_keys": missing_keys,
        "extra_keys": extra_keys,
    }


def _placeholders(value: str) -> list[str]:
    """Return format placeholders in stable order for contract comparison."""
    return sorted(_PLACEHOLDER_RE.findall(value))


def build_locale_matrix(
    locales_dir: Path,
    *,
    baseline_locale: str = "en",
) -> dict[str, Any]:
    """Build a parity/placeholder matrix for every shipped catalog.

    The baseline is the source of truth for keys and formatting contracts.
    Translation quality is intentionally not inferred: this report only
    proves structural parity, placeholder preservation, and branding class.
    """
    _, flattened = _build_catalogs(locales_dir)
    baseline = _resolve_requested_locale(baseline_locale, catalogs=flattened)
    baseline_values = flattened[baseline.canonical_locale]
    baseline_keys = set(baseline_values)
    catalogs: list[dict[str, Any]] = []
    for locale in sorted(flattened):
        values = flattened[locale]
        missing = sorted(baseline_keys - set(values))
        extra = sorted(set(values) - baseline_keys)
        placeholder_mismatches = [
            {
                "key": key,
                "baseline": _placeholders(baseline_values[key]),
                "locale": _placeholders(values[key]),
            }
            for key in sorted(baseline_keys & set(values))
            if _placeholders(baseline_values[key]) != _placeholders(values[key])
        ]
        catalogs.append({
            "locale": locale,
            "catalog_file": f"{locale}.yaml",
            "key_count": len(values),
            "missing_keys": missing,
            "extra_keys": extra,
            "placeholder_mismatches": placeholder_mismatches,
            "branding_classification": _classify_branding(list(values.values())),
            "ok": not missing and not extra and not placeholder_mismatches,
        })
    return {
        "schema": MATRIX_SCHEMA,
        "contract_version": CURRENT_CONTRACT_VERSION,
        "baseline_locale": baseline.requested_locale,
        "baseline_canonical_locale": baseline.canonical_locale,
        "catalogs": catalogs,
        "ok": all(catalog["ok"] for catalog in catalogs),
    }


def build_locale_receipt(
    locales_dir: Path,
    *,
    baseline_locale: str = "en-US",
    target_locale: str = "pt-BR",
    required_product_locales: tuple[str, ...] = REQUIRED_PRODUCT_LOCALES,
) -> dict[str, Any]:
    inventory = build_locale_inventory(
        locales_dir, required_product_locales=required_product_locales
    )
    parity = build_required_locale_parity(
        locales_dir, baseline_locale=baseline_locale, target_locale=target_locale
    )
    required_locales = inventory["required_product_locales"]
    return {
        "schema": RECEIPT_SCHEMA,
        "contract_version": CURRENT_CONTRACT_VERSION,
        "inventory_sha256": _sha256_text(_canonical_json(inventory)),
        "required_locales_ready": parity["key_parity"],
        "required_product_locales": [entry["requested_locale"] for entry in required_locales],
        "fallback_classification": {
            entry["requested_locale"]: entry["fallback_classification"]
            for entry in required_locales
        },
        "branding_classification": {
            entry["requested_locale"]: entry["branding_classification"]
            for entry in required_locales
        },
        "parity": parity,
    }


__all__ = [
    "CURRENT_CONTRACT_VERSION",
    "INVENTORY_SCHEMA",
    "PARITY_SCHEMA",
    "MATRIX_SCHEMA",
    "RECEIPT_SCHEMA",
    "REQUIRED_PRODUCT_LOCALES",
    "build_locale_inventory",
    "build_locale_receipt",
    "build_required_locale_parity",
    "build_locale_matrix",
]
