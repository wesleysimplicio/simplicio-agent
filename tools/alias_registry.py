"""Deterministic alias-registry loading and lookup for bounded deprecation slices.

The registry is intentionally standalone for issue #193: it models alias data,
validates collisions, and produces warning/receipt metadata without storing
invocation arguments or secrets. Public wiring stays outside this module.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

ALIAS_DOCUMENT_SCHEMA = "simplicio-agent/alias-registry/v1"
ALIAS_WARNING_SCHEMA = "simplicio-agent/alias-warning/v1"
ALIAS_RECEIPT_SCHEMA = "simplicio-agent/alias-receipt/v1"
ALIAS_DOCUMENT_VERSION = 1


class AliasRegistryError(ValueError):
    """Base class for alias-registry validation failures."""


class AliasSchemaError(AliasRegistryError):
    """Raised when an alias document does not satisfy the schema."""


class AliasCollisionError(AliasRegistryError):
    """Raised when two documents claim the same alias incompatibly."""


def normalize_alias(value: str) -> str:
    """Return the canonical lookup key for *value*."""

    return value.strip().casefold()


def _validate_date(raw: str, *, field_name: str, source: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise AliasSchemaError(
            f"{source}: {field_name} must be YYYY-MM-DD, got {raw!r}"
        ) from exc
    return raw


@dataclass(frozen=True)
class AliasEntry:
    alias: str
    canonical: str
    source: str
    owner: str = ""
    deprecated: bool = False
    warning_code: str = ""
    remove_after: str = ""
    note: str = ""

    @property
    def normalized_alias(self) -> str:
        return normalize_alias(self.alias)

    def removal_state(self, *, today: date) -> str:
        if not self.remove_after:
            return "none"
        return "due" if today >= date.fromisoformat(self.remove_after) else "scheduled"

    def signature(self) -> tuple[str, str, bool, str, str, str]:
        return (
            self.alias,
            self.canonical,
            self.deprecated,
            self.owner,
            self.warning_code,
            self.remove_after,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AliasWarning:
    alias: str
    canonical: str
    owner: str
    warning_code: str
    removal_state: str
    remove_after: str = ""
    source: str = ""
    schema: str = ALIAS_WARNING_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AliasReceipt:
    invoked_as: str
    canonical: str
    matched_alias: str = ""
    owner: str = ""
    warning_code: str = ""
    removal_state: str = "none"
    remove_after: str = ""
    source: str = ""
    deprecated: bool = False
    argv_count: int = 0
    args_redacted: bool = True
    schema: str = ALIAS_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AliasLookup:
    canonical: str
    entry: Optional[AliasEntry]
    warning: Optional[AliasWarning]
    receipt: AliasReceipt


class AliasRegistry:
    """Validated alias entries with deterministic lookup."""

    def __init__(self, entries: Iterable[AliasEntry]) -> None:
        ordered = sorted(
            entries,
            key=lambda entry: (entry.normalized_alias, entry.alias, entry.canonical, entry.source),
        )
        mapping: dict[str, AliasEntry] = {}
        for entry in ordered:
            current = mapping.get(entry.normalized_alias)
            if current is None:
                mapping[entry.normalized_alias] = entry
                continue
            if current.signature() != entry.signature():
                raise AliasCollisionError(
                    f"alias collision for {entry.alias!r}: "
                    f"{current.canonical!r} ({current.source}) vs "
                    f"{entry.canonical!r} ({entry.source})"
                )
            raise AliasCollisionError(
                f"duplicate alias registration for {entry.alias!r}: "
                f"{current.source} and {entry.source}"
            )
        self._entries = mapping

    @property
    def entries(self) -> tuple[AliasEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    @property
    def legacy_map(self) -> dict[str, str]:
        return {
            entry.alias: entry.canonical
            for entry in self.entries
            if entry.deprecated and entry.alias != entry.canonical
        }

    def lookup(
        self,
        argv: Sequence[str] | str,
        *,
        today: Optional[date] = None,
    ) -> AliasLookup:
        parts = [argv] if isinstance(argv, str) else list(argv)
        invoked_as = parts[0].strip() if parts else ""
        entry = self._entries.get(normalize_alias(invoked_as))
        today = today or date.today()
        if entry is None:
            receipt = AliasReceipt(
                invoked_as=invoked_as,
                canonical=invoked_as,
                argv_count=len(parts),
            )
            return AliasLookup(canonical=invoked_as, entry=None, warning=None, receipt=receipt)

        removal_state = entry.removal_state(today=today)
        warning = None
        if entry.deprecated:
            warning = AliasWarning(
                alias=entry.alias,
                canonical=entry.canonical,
                owner=entry.owner,
                warning_code=entry.warning_code or "deprecated_alias",
                removal_state=removal_state,
                remove_after=entry.remove_after,
                source=entry.source,
            )
        receipt = AliasReceipt(
            invoked_as=invoked_as,
            canonical=entry.canonical,
            matched_alias=entry.alias,
            owner=entry.owner,
            warning_code=warning.warning_code if warning else "",
            removal_state=removal_state,
            remove_after=entry.remove_after,
            source=entry.source,
            deprecated=entry.deprecated,
            argv_count=len(parts),
        )
        return AliasLookup(
            canonical=entry.canonical,
            entry=entry,
            warning=warning,
            receipt=receipt,
        )


def _parse_entry(raw: dict[str, Any], *, source: str) -> AliasEntry:
    alias = str(raw.get("alias", "")).strip()
    canonical = str(raw.get("canonical", "")).strip()
    if not alias or not canonical:
        raise AliasSchemaError(f"{source}: alias and canonical are required")

    deprecated = bool(raw.get("deprecated", False))
    owner = str(raw.get("owner", "")).strip()
    warning_code = str(raw.get("warning_code", "")).strip()
    remove_after = str(raw.get("remove_after", "")).strip()
    note = str(raw.get("note", "")).strip()

    if remove_after:
        remove_after = _validate_date(
            remove_after, field_name="remove_after", source=source
        )
    if deprecated and not owner:
        raise AliasSchemaError(f"{source}: deprecated alias {alias!r} requires owner")
    if remove_after and not deprecated:
        raise AliasSchemaError(
            f"{source}: remove_after requires deprecated=true for {alias!r}"
        )
    if owner and not deprecated:
        raise AliasSchemaError(
            f"{source}: owner is only valid for deprecated aliases ({alias!r})"
        )

    return AliasEntry(
        alias=alias,
        canonical=canonical,
        source=source,
        owner=owner,
        deprecated=deprecated,
        warning_code=warning_code,
        remove_after=remove_after,
        note=note,
    )


def load_alias_document(path: str | Path) -> tuple[AliasEntry, ...]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AliasSchemaError(f"{source}: invalid JSON") from exc

    schema = raw.get("schema")
    version = raw.get("version")
    if schema != ALIAS_DOCUMENT_SCHEMA:
        raise AliasSchemaError(
            f"{source}: expected schema {ALIAS_DOCUMENT_SCHEMA!r}, got {schema!r}"
        )
    if version != ALIAS_DOCUMENT_VERSION:
        raise AliasSchemaError(
            f"{source}: expected version {ALIAS_DOCUMENT_VERSION}, got {version!r}"
        )
    aliases = raw.get("aliases")
    if not isinstance(aliases, list):
        raise AliasSchemaError(f"{source}: aliases must be a list")
    return tuple(
        _parse_entry(item, source=str(source))
        for item in aliases
        if isinstance(item, dict)
    )


def load_alias_registry(root: str | Path) -> AliasRegistry:
    base = Path(root)
    files = sorted(base.rglob("*.json"))
    entries: list[AliasEntry] = []
    for path in files:
        entries.extend(load_alias_document(path))
    return AliasRegistry(entries)


__all__ = [
    "ALIAS_DOCUMENT_SCHEMA",
    "ALIAS_DOCUMENT_VERSION",
    "ALIAS_RECEIPT_SCHEMA",
    "ALIAS_WARNING_SCHEMA",
    "AliasCollisionError",
    "AliasEntry",
    "AliasLookup",
    "AliasReceipt",
    "AliasRegistry",
    "AliasRegistryError",
    "AliasSchemaError",
    "AliasWarning",
    "load_alias_document",
    "load_alias_registry",
    "normalize_alias",
]
