#!/usr/bin/env python3
"""addressing_geometry.py — Algorithms of Asolaria: Addressing Geometry.

Deterministic port of the Asolaria addressing primitives ("#12 Algorithms —
Addressing Geometry").  Every function here is a pure, reproducible transform —
no LLM, no network, no clock.  The primitives are the building blocks the
ecosystem uses to give every artifact (a module, a function, a file:line:col
site) a *locality-preserving* canonical key.

Primitives implemented:

  * REALMATHPOS  — real-math position: file:line:col collapsed to a monotone
                   numeric coordinate so that *adjacent* source sites stay
                   *adjacent* in the numeric space (locality preserved).
  * FNV-1a64    — fast non-cryptographic 64-bit hash of a file path (matches
                   the canonical FNV-1a/64 test vectors).
  * sha16        — canonical 16-hex module identifier (sha256[:16]).
  * citizenIdentity — the fused canonical identity of a source site:
                   CIT-<sha16(file)>-<tier><slot>[-tag].
  * 3 encoding tiers — 256 (8-bit), 1024 (10-bit), hyper (48-bit).  The small
                   tiers are pure locality-preserving (slot = pos mod range);
                   the hyper tier widens the space and mixes the file seed so a
                   single site can live in many address spaces.
  * Tagging discipline — every addressing claim carries a discipline tag:
                   MEASURED (read from a real file), CANON (derived identity),
                   UNVERIFIED (default until verified).  A verifier re-derives
                   the claim and refuses UNVERIFIED claims that fail to close.

The integrity face (this module): the citizen identity round-trips.  Given a
file:line:col and a tier, the same inputs always produce the same slot and the
same identity string; the verifier recomputes from the embedded file_id and
slot and rejects tampered/UNVERIFIED claims.

Hashing matches asolaria_hbi_hbp: sha256 -> first 16 hex chars per node id.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from typing import Literal

# --- FNV-1a / 64-bit constants --------------------------------------------
FNV_OFFSET_64 = 0xCBF29CE484222325
FNV_PRIME_64 = 0x100000001B3
MASK_64 = (1 << 64) - 1

# --- encoding tiers ---------------------------------------------------------
#  256   -> 8-bit  address space (slot 0..255)
#  1024  -> 10-bit address space (slot 0..1023)
#  hyper -> 48-bit address space (wide; mixes file seed)
TIER_RANGE: dict[str, int] = {"256": 256, "1024": 1024, "hyper": 1 << 48}
TIER_BITS: dict[str, int] = {"256": 8, "1024": 10, "hyper": 48}

# --- tagging discipline ------------------------------------------------------
TagKind = Literal["MEASURED", "CANON", "UNVERIFIED"]


def sha16(s: str) -> str:
    """Canonical 16-hex module identifier (sha256[:16])."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def fnv1a64(data: bytes | str) -> int:
    """FNV-1a 64-bit hash.  Matches canonical test vectors:
    b""        -> 0xCBF29CE484222325
    b"a"       -> 0xAF63DC4C8601EC8C
    b"foobar"  -> 0x85944171F73967E8
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    h = FNV_OFFSET_64
    for byte in data:
        h ^= byte
        h = (h * FNV_PRIME_64) & MASK_64
    return h


@dataclass(frozen=True)
class RealMathPos:
    """Real-math position of a source site.

    ``pos`` is monotone in (line, col): increasing either coordinate increases
    ``pos``, so the numeric space preserves source locality.  ``file_id`` is the
    canonical sha16 module identifier.
    """

    file_id: str
    line: int
    col: int
    pos: int

    def __str__(self) -> str:
        return f"{self.file_id}:{self.line}:{self.col}"


# Stride for the small (256/1024) tiers.  It must be coprime to both ranges so
# that a change in line OR col always shifts the slot (no collapse), while
# adjacent source sites stay adjacent in the address space.
_LOC_STRIDE = 1021  # prime, coprime to 256 and 1024


def realmathpos(file: str, line: int, col: int) -> RealMathPos:
    """Collapse file:line:col into a monotone coordinate.

    ``pos = line * 4096 + col`` is a monotone (and human-readable) canonical
    coordinate: increasing either ``line`` or ``col`` strictly increases ``pos``.
    The encoding tiers below fold this into a locality-preserving slot.
    ``file_id`` is the canonical sha16 of the file path.
    """
    if line < 0 or col < 0:
        raise ValueError(f"line/col must be >= 0, got ({line}, {col})")
    return RealMathPos(
        file_id=sha16(file),
        line=line,
        col=col,
        pos=line * 4096 + col,
    )


def encode_addr(tier: str, file: str, line: int, col: int) -> int:
    """Locality-preserving slot for ``(file, line, col)`` in ``tier``.

    * 256 / 1024: pure locality-preserving — slot = (line*STRIDE + col) mod
      range, with STRIDE coprime to the range, so nearby lines/cols land in
      nearby slots and adjacent sites never collapse onto the same slot.
    * hyper: wide 48-bit space; mixes the file seed with the monotone position
      so the same site is stable across runs while spreading across the space.
    """
    if tier not in TIER_RANGE:
        raise ValueError(f"unknown tier {tier!r}; expected one of {list(TIER_RANGE)}")
    if tier == "hyper":
        pos = realmathpos(file, line, col).pos
        seed = fnv1a64(file)
        # 48-bit blend: file seed high, monotone position low -> stable & wide.
        return ((seed << 20) ^ (pos * 0x9E3779B97F4A7C15)) & ((1 << 48) - 1)
    return (line * _LOC_STRIDE + col) % TIER_RANGE[tier]


@dataclass(frozen=True)
class CitizenIdentity:
    """Fused canonical identity of a source site."""

    file_id: str
    tier: str
    slot: int
    tag: TagKind
    token: str

    def __str__(self) -> str:
        return self.token


def citizen_identity(
    file: str,
    line: int,
    col: int,
    tier: str = "1024",
    tag: TagKind = "CANON",
) -> CitizenIdentity:
    """Build the canonical CIT-<file_id>-<tier><slot>[-tag] identity."""
    if tier not in TIER_RANGE:
        raise ValueError(f"unknown tier {tier!r}; expected one of {list(TIER_RANGE)}")
    rmp = realmathpos(file, line, col)
    slot = encode_addr(tier, file, line, col)
    slot_hex = f"{slot:0{TIER_BITS[tier] // 4}x}"
    token = f"CIT-{rmp.file_id}-{tier}{slot_hex}-{tag}"
    return CitizenIdentity(
        file_id=rmp.file_id, tier=tier, slot=slot, tag=tag, token=token
    )


@dataclass(frozen=True)
class Tagged:
    """An addressing claim carrying its discipline tag."""

    value: object
    tag: TagKind
    note: str

    @property
    def verified(self) -> bool:
        return self.tag != "UNVERIFIED"


def tag(value: object, kind: TagKind, note: str = "") -> Tagged:
    """Attach a discipline tag to an addressing claim."""
    if kind not in ("MEASURED", "CANON", "UNVERIFIED"):
        raise ValueError(f"unknown tag kind {kind!r}")
    return Tagged(value=value, tag=kind, note=note)


def verify_citizen(cit: CitizenIdentity, file: str, line: int, col: int) -> bool:
    """Re-derive the citizen identity from raw inputs and close the round-trip.

    A tampered token (wrong file, line, col, tier, or tag) fails to close.
    An UNVERIFIED token is rejected even when it round-trips.
    """
    recomputed = citizen_identity(file, line, col, tier=cit.tier, tag=cit.tag)
    if recomputed.token != cit.token:
        return False
    return cit.tag != "UNVERIFIED"


def selftest() -> int:
    # 1) sha16: deterministic, 16 hex chars.
    a = sha16("simplicio_agent/asolaria.py")
    b = sha16("simplicio_agent/asolaria.py")
    assert len(a) == 16 and a == b, "sha16 not stable/16-hex"
    assert sha16("x") != sha16("y"), "sha16 collision"

    # 2) FNV-1a64 matches canonical test vectors.
    assert fnv1a64(b"") == 0xCBF29CE484222325, "fnv1a64 empty vector"
    assert fnv1a64(b"a") == 0xAF63DC4C8601EC8C, "fnv1a64 'a' vector"
    assert fnv1a64(b"foobar") == 0x85944171F73967E8, "fnv1a64 'foobar' vector"

    # 3) REALMATHPOS: monotone in line/col (locality preserved).
    p0 = realmathpos("mod.py", 10, 5)
    p1 = realmathpos("mod.py", 11, 5)
    p2 = realmathpos("mod.py", 10, 6)
    assert p1.pos > p0.pos > 0, "line must increase pos"
    assert p2.pos > p0.pos, "col must increase pos"
    assert p0.file_id == sha16("mod.py"), "file_id must be sha16(file)"

    # 4) 3 tiers: valid slot ranges.
    for tier, rng in (("256", 256), ("1024", 1024), ("hyper", 1 << 48)):
        s = encode_addr(tier, "mod.py", 3, 7)
        assert 0 <= s < rng, f"tier {tier} slot out of range: {s}"

    # 5) Locality: adjacent lines land in adjacent 256/1024 slots.
    #    stride 1021 is coprime to both ranges, so step = 1021 mod range
    #    and a single-line step shifts the slot by exactly that (no wrap-to-0).
    base = encode_addr("256", "mod.py", 10, 0)
    step = encode_addr("256", "mod.py", 11, 0)
    assert (step - base) % 256 == 1021 % 256, "256-tier not locality-preserving"
    base10 = encode_addr("1024", "mod.py", 10, 0)
    step10 = encode_addr("1024", "mod.py", 11, 0)
    assert (step10 - base10) % 1024 == 1021 % 1024, "1024-tier not locality-preserving"

    # 5b) col step also shifts the slot (no collapse across lines).
    col0 = encode_addr("256", "mod.py", 10, 0)
    col1 = encode_addr("256", "mod.py", 10, 1)
    assert (col1 - col0) % 256 == 1, "256-tier col not locality-preserving"

    # 5c) hyper tier is stable across runs but wide (>= 2**40).
    h0 = encode_addr("hyper", "mod.py", 10, 0)
    h1 = encode_addr("hyper", "mod.py", 10, 0)
    assert h0 == h1 and h0 >= (1 << 40), "hyper tier not stable/wide"

    # 6) citizen_identity: deterministic + round-trips through verify_citizen.
    c = citizen_identity("mod.py", 42, 7, tier="1024", tag="CANON")
    c2 = citizen_identity("mod.py", 42, 7, tier="1024", tag="CANON")
    assert c.token == c2.token, "citizen identity not deterministic"
    assert c.token.startswith(f"CIT-{sha16('mod.py')}-1024"), "token format"
    assert verify_citizen(c, "mod.py", 42, 7) is True, "CANNON claim must verify"

    # 7) Tamper: wrong line/col/file fails the round-trip.
    assert verify_citizen(c, "mod.py", 43, 7) is False, "line tamper must fail"
    assert verify_citizen(c, "other.py", 42, 7) is False, "file tamper must fail"

    # 8) Tagging discipline: UNVERIFIED is rejected even when it round-trips.
    u = citizen_identity("mod.py", 42, 7, tier="1024", tag="UNVERIFIED")
    assert u.tag == "UNVERIFIED"
    assert verify_citizen(u, "mod.py", 42, 7) is False, "UNVERIFIED must not verify"
    t = tag(c.token, "MEASURED", note="read from real source")
    assert t.verified is True and t.tag == "MEASURED", "MEASURED must verify"

    print(
        "ADDRESSING-GEOMETRY|realmathpos=PASS|fnv1a64=PASS|sha16=PASS|"
        f"tiers=3/3|locality=PASS|roundtrip=PASS|tamper=CAUGHT|"
        f"tagging=PASS|PASS"
    )
    return 0


if __name__ == "__main__":
    if "--selftest" not in sys.argv:
        raise SystemExit("usage: python -m addressing_geometry --selftest")
    raise SystemExit(selftest())
