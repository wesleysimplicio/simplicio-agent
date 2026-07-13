"""Deterministic CLI/TUI public-surface identity contract for issue #188.

This module does not inspect or mutate live CLI/TUI implementations. It defines
the bounded contract documents that those surfaces are expected to follow:

- `simplicio-agent` is the only canonical user-facing command name.
- `hermes*` aliases remain migration-only compatibility shims.
- public messages are classified deterministically from their surface text.
- receipts must be safe to persist: no raw argv, tokens, or secret-bearing keys.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.alias_registry import CLI_ALIAS_CANONICAL, default_cli_alias_entries

CLI_SURFACE_MANIFEST_SCHEMA = "simplicio-agent/cli-surface-manifest/v1"
CLI_SURFACE_CHECK_SCHEMA = "simplicio-agent/cli-surface-check/v1"
CLI_SURFACE_RECEIPT_SCHEMA = "simplicio-agent/cli-surface-receipt/v1"
CLI_SURFACE_VERSION = 1
CANONICAL_COMMAND = CLI_ALIAS_CANONICAL
MIGRATION_ONLY = "migration_only"
ALLOWED_MESSAGE_CLASSIFICATIONS = frozenset(
    {"canonical_hint", "migration_notice", "branding_event", "neutral_public_text"}
)
_LEGACY_ALIASES = tuple(entry.alias for entry in default_cli_alias_entries())
_SENSITIVE_KEY_TOKENS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "bearer",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}\b", re.IGNORECASE),
)


class CliSurfaceContractError(ValueError):
    """Base class for contract/fixture validation failures."""


class CliSurfaceSchemaError(CliSurfaceContractError):
    """Raised when a manifest violates the contract schema."""


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _contains_legacy_alias(text: str) -> bool:
    lowered = text.casefold()
    return any(alias in lowered for alias in _LEGACY_ALIASES)


def _command_mentions(text: str) -> set[str]:
    lowered = text.casefold()
    mentions: set[str] = set()
    if CANONICAL_COMMAND in lowered:
        mentions.add(CANONICAL_COMMAND)
    for alias in _LEGACY_ALIASES:
        if alias in lowered:
            mentions.add(alias)
    return mentions


def classify_public_message(*, message_id: str, surface: str, text: str) -> str:
    """Return the deterministic public classification for a surface message."""

    mid = _trim(message_id).casefold()
    sfc = _trim(surface).casefold()
    body = _trim(text).casefold()

    if "deprecated alias" in body or "same cli, new name" in body or "alias" in mid:
        return "migration_notice"
    if sfc == "tui" and (mid in {"gateway.ready", "skin.changed"} or "branding" in body):
        return "branding_event"
    if CANONICAL_COMMAND in body:
        return "canonical_hint"
    return "neutral_public_text"


def _find_sensitive_paths(value: Any, *, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            lowered = key_text.casefold()
            if any(token in lowered for token in _SENSITIVE_KEY_TOKENS):
                findings.append(path)
            findings.extend(_find_sensitive_paths(nested, prefix=path))
        return findings
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]"
            findings.extend(_find_sensitive_paths(nested, prefix=path))
        return findings
    text = str(value)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            findings.append(prefix or "<value>")
            break
    return findings


@dataclass(frozen=True)
class LegacyAlias:
    alias: str
    canonical: str
    policy: str
    owner: str
    warning_code: str
    notice: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublicMessage:
    message_id: str
    surface: str
    text: str
    classification: str

    def derived_classification(self) -> str:
        return classify_public_message(
            message_id=self.message_id,
            surface=self.surface,
            text=self.text,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiptSample:
    receipt_id: str
    payload: Mapping[str, Any]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["payload"] = dict(self.payload)
        data["notes"] = list(self.notes)
        return data


@dataclass(frozen=True)
class CliSurfaceManifest:
    canonical_command: str
    canonical_help_commands: tuple[str, ...]
    legacy_aliases: tuple[LegacyAlias, ...]
    public_messages: tuple[PublicMessage, ...]
    receipts: tuple[ReceiptSample, ...]
    schema: str = CLI_SURFACE_MANIFEST_SCHEMA
    version: int = CLI_SURFACE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "canonical_command": self.canonical_command,
            "canonical_help_commands": list(self.canonical_help_commands),
            "legacy_aliases": [entry.to_dict() for entry in self.legacy_aliases],
            "public_messages": [entry.to_dict() for entry in self.public_messages],
            "receipts": [entry.to_dict() for entry in self.receipts],
        }


def default_manifest() -> CliSurfaceManifest:
    return CliSurfaceManifest(
        canonical_command=CANONICAL_COMMAND,
        canonical_help_commands=(
            "simplicio-agent doctor",
            "simplicio-agent gateway start",
            "simplicio-agent --tui",
        ),
        legacy_aliases=tuple(
            LegacyAlias(
                alias=entry.alias,
                canonical=entry.canonical,
                policy=MIGRATION_ONLY,
                owner=entry.owner,
                warning_code=entry.warning_code,
                notice="same CLI, new name",
            )
            for entry in default_cli_alias_entries()
        ),
        public_messages=(
            PublicMessage(
                message_id="cli.deprecated_alias_notice",
                surface="cli",
                text="note: `hermes` is a deprecated alias; use `simplicio-agent` (same CLI, new name).",
                classification="migration_notice",
            ),
            PublicMessage(
                message_id="cli.help.doctor",
                surface="cli",
                text="Run `simplicio-agent doctor` for diagnostics.",
                classification="canonical_hint",
            ),
            PublicMessage(
                message_id="gateway.ready",
                surface="tui",
                text="gateway.ready publishes branding.agent_name=Simplicio Agent.",
                classification="branding_event",
            ),
            PublicMessage(
                message_id="skin.changed",
                surface="tui",
                text="skin.changed refreshes branding fields for the TUI.",
                classification="branding_event",
            ),
        ),
        receipts=(
            ReceiptSample(
                receipt_id="alias-warning-receipt",
                payload={
                    "schema": CLI_SURFACE_RECEIPT_SCHEMA,
                    "canonical": CANONICAL_COMMAND,
                    "warning_code": "deprecated_cli_alias",
                    "argv_count": 3,
                    "args_redacted": True,
                    "raw_argv": None,
                },
                notes=("safe_fields_only",),
            ),
        ),
    )


def manifest_from_dict(raw: Mapping[str, Any]) -> CliSurfaceManifest:
    return CliSurfaceManifest(
        schema=str(raw.get("schema", "")).strip(),
        version=int(raw.get("version", 0)),
        canonical_command=str(raw.get("canonical_command", "")).strip(),
        canonical_help_commands=tuple(
            str(item).strip() for item in raw.get("canonical_help_commands", [])
        ),
        legacy_aliases=tuple(
            LegacyAlias(
                alias=str(item.get("alias", "")).strip(),
                canonical=str(item.get("canonical", "")).strip(),
                policy=str(item.get("policy", "")).strip(),
                owner=str(item.get("owner", "")).strip(),
                warning_code=str(item.get("warning_code", "")).strip(),
                notice=str(item.get("notice", "")).strip(),
            )
            for item in raw.get("legacy_aliases", [])
            if isinstance(item, Mapping)
        ),
        public_messages=tuple(
            PublicMessage(
                message_id=str(item.get("message_id", "")).strip(),
                surface=str(item.get("surface", "")).strip(),
                text=str(item.get("text", "")).strip(),
                classification=str(item.get("classification", "")).strip(),
            )
            for item in raw.get("public_messages", [])
            if isinstance(item, Mapping)
        ),
        receipts=tuple(
            ReceiptSample(
                receipt_id=str(item.get("receipt_id", "")).strip(),
                payload=item.get("payload", {}) if isinstance(item.get("payload"), Mapping) else {},
                notes=tuple(str(note).strip() for note in item.get("notes", [])),
            )
            for item in raw.get("receipts", [])
            if isinstance(item, Mapping)
        ),
    )


def load_manifest(path: str | Path) -> CliSurfaceManifest:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliSurfaceSchemaError(f"{source}: invalid JSON") from exc
    return manifest_from_dict(raw)


def check_manifest(manifest: CliSurfaceManifest) -> dict[str, Any]:
    errors: list[str] = []

    if manifest.schema != CLI_SURFACE_MANIFEST_SCHEMA:
        errors.append(
            f"schema must be {CLI_SURFACE_MANIFEST_SCHEMA!r}, got {manifest.schema!r}"
        )
    if manifest.version != CLI_SURFACE_VERSION:
        errors.append(
            f"version must be {CLI_SURFACE_VERSION}, got {manifest.version}"
        )
    if manifest.canonical_command != CANONICAL_COMMAND:
        errors.append(
            f"canonical_command must be {CANONICAL_COMMAND!r}, got {manifest.canonical_command!r}"
        )

    for command in manifest.canonical_help_commands:
        if not command.startswith(f"{CANONICAL_COMMAND} "):
            errors.append(
                f"canonical_help_commands must start with {CANONICAL_COMMAND!r}: {command!r}"
            )
        if _contains_legacy_alias(command):
            errors.append(f"canonical_help_commands may not mention legacy aliases: {command!r}")

    seen_aliases: set[str] = set()
    for alias in manifest.legacy_aliases:
        if not alias.alias:
            errors.append("legacy alias entries require alias")
            continue
        norm = alias.alias.casefold()
        if norm in seen_aliases:
            errors.append(f"duplicate legacy alias {alias.alias!r}")
        seen_aliases.add(norm)
        if alias.alias == CANONICAL_COMMAND:
            errors.append("canonical command may not appear in legacy_aliases")
        if alias.canonical != CANONICAL_COMMAND:
            errors.append(
                f"legacy alias {alias.alias!r} must map to {CANONICAL_COMMAND!r}"
            )
        if alias.policy != MIGRATION_ONLY:
            errors.append(
                f"legacy alias {alias.alias!r} must be {MIGRATION_ONLY!r}, got {alias.policy!r}"
            )
        if not alias.owner:
            errors.append(f"legacy alias {alias.alias!r} requires owner")
        if not alias.warning_code:
            errors.append(f"legacy alias {alias.alias!r} requires warning_code")

    for message in manifest.public_messages:
        derived = message.derived_classification()
        if message.classification not in ALLOWED_MESSAGE_CLASSIFICATIONS:
            errors.append(
                f"message {message.message_id!r} has unknown classification {message.classification!r}"
            )
        if message.classification != derived:
            errors.append(
                f"message {message.message_id!r} classification must be {derived!r}, got {message.classification!r}"
            )
        mentions = _command_mentions(message.text)
        if message.classification != "migration_notice" and mentions.intersection(_LEGACY_ALIASES):
            errors.append(
                f"message {message.message_id!r} mentions legacy alias outside migration_notice"
            )
        if message.classification in {"canonical_hint", "migration_notice"} and CANONICAL_COMMAND not in mentions:
            errors.append(
                f"message {message.message_id!r} must mention {CANONICAL_COMMAND!r}"
            )

    for receipt in manifest.receipts:
        payload = dict(receipt.payload)
        if payload.get("schema") != CLI_SURFACE_RECEIPT_SCHEMA:
            errors.append(
                f"receipt {receipt.receipt_id!r} must use schema {CLI_SURFACE_RECEIPT_SCHEMA!r}"
            )
        if payload.get("raw_argv") not in (None, [], ""):
            errors.append(f"receipt {receipt.receipt_id!r} may not persist raw_argv")
        sensitive_paths = _find_sensitive_paths(payload)
        if sensitive_paths:
            errors.append(
                f"receipt {receipt.receipt_id!r} leaks sensitive fields: {', '.join(sorted(sensitive_paths))}"
            )
        if payload.get("args_redacted") is not True:
            errors.append(f"receipt {receipt.receipt_id!r} must set args_redacted=true")

    return {
        "schema": CLI_SURFACE_CHECK_SCHEMA,
        "ok": not errors,
        "error_count": len(errors),
        "errors": errors,
        "canonical_command": manifest.canonical_command,
        "legacy_alias_count": len(manifest.legacy_aliases),
        "public_message_count": len(manifest.public_messages),
        "receipt_count": len(manifest.receipts),
    }


def validate_manifest(manifest: CliSurfaceManifest) -> CliSurfaceManifest:
    report = check_manifest(manifest)
    if report["ok"]:
        return manifest
    joined = "; ".join(report["errors"])
    raise CliSurfaceSchemaError(joined)


__all__ = [
    "ALLOWED_MESSAGE_CLASSIFICATIONS",
    "CANONICAL_COMMAND",
    "CLI_SURFACE_CHECK_SCHEMA",
    "CLI_SURFACE_MANIFEST_SCHEMA",
    "CLI_SURFACE_RECEIPT_SCHEMA",
    "CLI_SURFACE_VERSION",
    "CliSurfaceContractError",
    "CliSurfaceManifest",
    "CliSurfaceSchemaError",
    "LegacyAlias",
    "MIGRATION_ONLY",
    "PublicMessage",
    "ReceiptSample",
    "check_manifest",
    "classify_public_message",
    "default_manifest",
    "load_manifest",
    "manifest_from_dict",
    "validate_manifest",
]
