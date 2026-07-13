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
