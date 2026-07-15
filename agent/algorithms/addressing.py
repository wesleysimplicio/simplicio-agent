"""
Algorithms — Addressing Geometry
=================================
Implements REALMATHPOS, FNV-1a64, sha16, and 3-tier resolution
as specified in Issue #36 (Algorithms of Asolaria).

Tagging discipline:
- MEASURED  : value derived from real file/runtime data
- CANON     : value is the canonical identifier (sha16, fnv)
- UNVERIFIED: value was supplied externally without verification
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Tagging discipline
# ---------------------------------------------------------------------------


class AddressTag(str, Enum):
    MEASURED = "MEASURED"
    CANON = "CANON"
    UNVERIFIED = "UNVERIFIED"


# ---------------------------------------------------------------------------
# REALMATHPOS — opaque position type (file:line:col)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class REALMATHPOS:
    """Opaque coordinate in source space: file path + line + column.

    Values are 1-indexed (line 1, col 1 = first character).
    The type is intentionally opaque — callers should not interpret
    the numeric fields beyond equality and ordering.
    """

    file: str
    line: int
    col: int
    tag: AddressTag = AddressTag.MEASURED

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}"

    def __repr__(self) -> str:
        return f"REALMATHPOS({self.file!r}, {self.line}, {self.col}, tag={self.tag.value})"

    @classmethod
    def from_string(cls, s: str, tag: AddressTag = AddressTag.UNVERIFIED) -> "REALMATHPOS":
        """Parse 'path:line:col' notation."""
        parts = s.rsplit(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid REALMATHPOS string: {s!r}")
        file, line, col = parts
        return cls(file=file, line=int(line), col=int(col), tag=tag)


# ---------------------------------------------------------------------------
# FNV-1a 64-bit hash of file paths
# ---------------------------------------------------------------------------

_FNV1A64_OFFSET = 14695981039346656037  # 2^64 - uses unsigned wrap
_FNV1A64_PRIME = 1099511628211
_FNV1A64_MOD = 2**64


def fnv1a64(path: str | Path) -> int:
    """FNV-1a 64-bit hash of a file path string.

    Returns an unsigned 64-bit integer (0 … 2^64-1).
    Tag: CANON — deterministic, collision-resistant for path keys.
    """
    if isinstance(path, Path):
        path = str(path)
    data = path.encode("utf-8")
    h = _FNV1A64_OFFSET
    for byte in data:
        h ^= byte
        h = (h * _FNV1A64_PRIME) % _FNV1A64_MOD
    return h


def fnv1a64_hex(path: str | Path) -> str:
    """FNV-1a 64-bit hash as a 16-character lowercase hex string."""
    return f"{fnv1a64(path):016x}"


# ---------------------------------------------------------------------------
# sha16 — canonical module identifier (first 8 bytes of SHA-256 in hex)
# ---------------------------------------------------------------------------


def sha16(content: str | bytes, tag: AddressTag = AddressTag.CANON) -> str:
    """Compute the canonical module identifier.

    Takes the first 8 bytes (64 bits) of SHA-256 and returns them as a
    16-character lowercase hex string.  This is the CANON identifier for
    a module or blob; callers are responsible for providing the correct
    canonical form of `content`.

    Tag: CANON by default (caller asserts canonical input).
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    digest = hashlib.sha256(content).digest()
    return digest[:8].hex()


# ---------------------------------------------------------------------------
# 3-Tier Resolution: local → project → global
# ---------------------------------------------------------------------------


class ResolutionTier(str, Enum):
    LOCAL = "local"      # within the current file / function scope
    PROJECT = "project"  # within the project / repository
    GLOBAL = "global"    # cross-repository / registry-wide


@dataclass
class AddressRecord:
    """A resolved address with provenance."""

    pos: REALMATHPOS
    tier: ResolutionTier
    module_id: str  # sha16 of the containing module
    path_hash: str  # fnv1a64_hex of the file path
    tag: AddressTag = AddressTag.MEASURED
    metadata: dict[str, Any] = field(default_factory=dict)


class AddressResolver:
    """3-tier address resolver: local → project → global.

    Resolution algorithm
    --------------------
    1. LOCAL   — check the in-memory local registry (per-file cache).
    2. PROJECT — check the project-wide index (typically a dict keyed by
                 sha16 of file content or module name).
    3. GLOBAL  — fall back to a pluggable global registry (default: empty).

    Callers register entries at each tier with `register()`.
    """

    def __init__(self) -> None:
        self._local: dict[str, AddressRecord] = {}
        self._project: dict[str, AddressRecord] = {}
        self._global: dict[str, AddressRecord] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        key: str,
        record: AddressRecord,
        tier: ResolutionTier = ResolutionTier.LOCAL,
    ) -> None:
        """Register an address record at the given tier."""
        target = self._tier_dict(tier)
        target[key] = record

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, key: str) -> Optional[tuple[AddressRecord, ResolutionTier]]:
        """Resolve a key through local → project → global tiers.

        Returns (record, tier) on success, or None if not found.
        """
        for tier, store in [
            (ResolutionTier.LOCAL, self._local),
            (ResolutionTier.PROJECT, self._project),
            (ResolutionTier.GLOBAL, self._global),
        ]:
            if key in store:
                return store[key], tier
        return None

    def resolve_tier(self, key: str) -> Optional[ResolutionTier]:
        """Return just the tier at which a key is first found."""
        result = self.resolve(key)
        return result[1] if result else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tier_dict(self, tier: ResolutionTier) -> dict[str, AddressRecord]:
        if tier == ResolutionTier.LOCAL:
            return self._local
        if tier == ResolutionTier.PROJECT:
            return self._project
        return self._global

    def make_record(
        self,
        pos: REALMATHPOS,
        content: str | bytes,
        tier: ResolutionTier = ResolutionTier.LOCAL,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AddressRecord:
        """Convenience factory: build an AddressRecord from a position and content."""
        return AddressRecord(
            pos=pos,
            tier=tier,
            module_id=sha16(content),
            path_hash=fnv1a64_hex(pos.file),
            tag=pos.tag,
            metadata=metadata or {},
        )
