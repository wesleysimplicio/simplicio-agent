"""Public source-checkout surface for issue #125."""

from __future__ import annotations

from simplicio_agent import asolaria


def test_public_n_nest_facade_preserves_corrective_gate():
    clean = asolaria.run_n_nest()
    tampered = asolaria.run_n_nest("R.0.0.0")

    assert clean.subtree_ok is True
    assert tampered.subtree_ok is False
    assert "R.0.0.0@depth3" in tampered.fail


def test_public_prism_facade_preserves_round_trip_and_capacity_gate():
    addr = "R.0.0.0"
    value = asolaria.prism_forward(addr)
    reported = asolaria.prism_seal(value)

    assert asolaria.prism_inverse(addr, reported) == (True, value)
    assert asolaria.prism_inverse(addr, "confabulated") == (False, value)

    capacity = asolaria.prism_crt_capacity()
    residues = asolaria.prism_crt_decompose(capacity - 1)
    assert asolaria.prism_crt_recombine(residues, domain_size=capacity) == (
        "ok",
        capacity - 1,
    )
    assert asolaria.prism_crt_recombine(residues, domain_size=capacity + 1) == (
        "held",
        None,
    )


def test_public_selftest():
    assert asolaria.selftest() == 0


# --- issue #36: Addressing Geometry ----------------------------------------
def test_addressing_realmathpos_locality():
    from simplicio_agent.asolaria import realmathpos

    p0 = realmathpos("mod.py", 10, 5)
    p1 = realmathpos("mod.py", 11, 5)
    p2 = realmathpos("mod.py", 10, 6)
    assert p1.pos > p0.pos > 0
    assert p2.pos > p0.pos
    assert p0.file_id == asolaria.sha16("mod.py")


def test_addressing_fnv1a64_vectors():
    assert asolaria.fnv1a64(b"") == 0xCBF29CE484222325
    assert asolaria.fnv1a64(b"a") == 0xAF63DC4C8601EC8C
    assert asolaria.fnv1a64(b"foobar") == 0x85944171F73967E8


def test_addressing_tiers_in_range():
    for tier, rng in (("256", 256), ("1024", 1024), ("hyper", 1 << 48)):
        slot = asolaria.encode_addr(tier, "mod.py", 3, 7)
        assert 0 <= slot < rng


def test_addressing_citizen_roundtrip_and_tamper():
    cit = asolaria.citizen_identity("mod.py", 42, 7, tier="1024", tag="CANON")
    assert asolaria.verify_citizen(cit, "mod.py", 42, 7) is True
    assert asolaria.verify_citizen(cit, "mod.py", 43, 7) is False
    assert asolaria.verify_citizen(cit, "other.py", 42, 7) is False


def test_addressing_unverified_rejected():
    unverified = asolaria.citizen_identity(
        "mod.py", 42, 7, tier="1024", tag="UNVERIFIED"
    )
    assert unverified.tag == "UNVERIFIED"
    assert asolaria.verify_citizen(unverified, "mod.py", 42, 7) is False
