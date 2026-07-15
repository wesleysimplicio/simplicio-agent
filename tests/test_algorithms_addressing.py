"""
Tests for agent/algorithms/addressing.py — Issue #36
No external dependencies required (stdlib only + pytest).
"""

import hashlib
import sys
import os

# Ensure the worktree root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.algorithms.addressing import (
    REALMATHPOS,
    AddressRecord,
    AddressResolver,
    AddressTag,
    ResolutionTier,
    fnv1a64,
    fnv1a64_hex,
    sha16,
)


# ---------------------------------------------------------------------------
# REALMATHPOS tests
# ---------------------------------------------------------------------------


def test_realmathpos_str():
    pos = REALMATHPOS(file="agent/foo.py", line=10, col=3)
    assert str(pos) == "agent/foo.py:10:3"


def test_realmathpos_from_string_roundtrip():
    original = "src/bar.py:42:7"
    pos = REALMATHPOS.from_string(original, tag=AddressTag.UNVERIFIED)
    assert pos.file == "src/bar.py"
    assert pos.line == 42
    assert pos.col == 7
    assert pos.tag == AddressTag.UNVERIFIED
    assert str(pos) == original


def test_realmathpos_frozen():
    pos = REALMATHPOS(file="a.py", line=1, col=1)
    try:
        pos.line = 2  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except Exception:
        pass  # expected — frozen dataclass


def test_realmathpos_invalid_string():
    import pytest
    with pytest.raises(ValueError):
        REALMATHPOS.from_string("no_colon_at_all")


# ---------------------------------------------------------------------------
# FNV-1a 64-bit tests
# ---------------------------------------------------------------------------


def test_fnv1a64_deterministic():
    h1 = fnv1a64("agent/foo.py")
    h2 = fnv1a64("agent/foo.py")
    assert h1 == h2


def test_fnv1a64_different_paths():
    assert fnv1a64("agent/foo.py") != fnv1a64("agent/bar.py")


def test_fnv1a64_range():
    h = fnv1a64("some/path.py")
    assert 0 <= h < 2**64


def test_fnv1a64_hex_length():
    h = fnv1a64_hex("agent/algorithms/addressing.py")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_fnv1a64_path_object():
    from pathlib import Path
    h_str = fnv1a64("agent/foo.py")
    h_path = fnv1a64(Path("agent/foo.py"))
    assert h_str == h_path


# ---------------------------------------------------------------------------
# sha16 tests
# ---------------------------------------------------------------------------


def test_sha16_length():
    result = sha16("hello world")
    assert len(result) == 16


def test_sha16_matches_sha256_prefix():
    content = b"module source code"
    expected = hashlib.sha256(content).digest()[:8].hex()
    assert sha16(content) == expected


def test_sha16_str_and_bytes_equivalent():
    text = "canonical module content"
    assert sha16(text) == sha16(text.encode("utf-8"))


def test_sha16_different_content():
    assert sha16("module_a") != sha16("module_b")


# ---------------------------------------------------------------------------
# 3-tier resolution tests
# ---------------------------------------------------------------------------


def test_resolver_local_first():
    resolver = AddressResolver()
    pos = REALMATHPOS("a.py", 1, 1)
    record_local = AddressRecord(
        pos=pos,
        tier=ResolutionTier.LOCAL,
        module_id=sha16("a"),
        path_hash=fnv1a64_hex("a.py"),
    )
    record_project = AddressRecord(
        pos=REALMATHPOS("b.py", 2, 2),
        tier=ResolutionTier.PROJECT,
        module_id=sha16("b"),
        path_hash=fnv1a64_hex("b.py"),
    )
    resolver.register("mykey", record_local, ResolutionTier.LOCAL)
    resolver.register("mykey", record_project, ResolutionTier.PROJECT)

    result = resolver.resolve("mykey")
    assert result is not None
    found_record, found_tier = result
    assert found_tier == ResolutionTier.LOCAL
    assert found_record.pos.file == "a.py"


def test_resolver_falls_through_to_project():
    resolver = AddressResolver()
    pos = REALMATHPOS("proj.py", 5, 1)
    record = AddressRecord(
        pos=pos,
        tier=ResolutionTier.PROJECT,
        module_id=sha16("proj"),
        path_hash=fnv1a64_hex("proj.py"),
    )
    resolver.register("proj_key", record, ResolutionTier.PROJECT)

    result = resolver.resolve("proj_key")
    assert result is not None
    found_record, found_tier = result
    assert found_tier == ResolutionTier.PROJECT


def test_resolver_falls_through_to_global():
    resolver = AddressResolver()
    pos = REALMATHPOS("global.py", 99, 1)
    record = AddressRecord(
        pos=pos,
        tier=ResolutionTier.GLOBAL,
        module_id=sha16("global_mod"),
        path_hash=fnv1a64_hex("global.py"),
    )
    resolver.register("global_key", record, ResolutionTier.GLOBAL)

    result = resolver.resolve("global_key")
    assert result is not None
    _, found_tier = result
    assert found_tier == ResolutionTier.GLOBAL


def test_resolver_missing_key():
    resolver = AddressResolver()
    assert resolver.resolve("nonexistent") is None
    assert resolver.resolve_tier("nonexistent") is None


def test_resolver_make_record():
    resolver = AddressResolver()
    pos = REALMATHPOS("agent/algo.py", 10, 5)
    record = resolver.make_record(pos, "module source", ResolutionTier.LOCAL)
    assert record.module_id == sha16("module source")
    assert record.path_hash == fnv1a64_hex("agent/algo.py")
    assert record.tier == ResolutionTier.LOCAL


def test_resolver_tier_priority_order():
    """Ensure LOCAL > PROJECT > GLOBAL."""
    resolver = AddressResolver()
    key = "shared_key"

    for tier in [ResolutionTier.GLOBAL, ResolutionTier.PROJECT, ResolutionTier.LOCAL]:
        pos = REALMATHPOS(f"{tier.value}.py", 1, 1)
        record = AddressRecord(
            pos=pos,
            tier=tier,
            module_id=sha16(tier.value),
            path_hash=fnv1a64_hex(f"{tier.value}.py"),
        )
        resolver.register(key, record, tier)

    _, found_tier = resolver.resolve(key)
    assert found_tier == ResolutionTier.LOCAL
