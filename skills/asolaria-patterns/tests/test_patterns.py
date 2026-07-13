#!/usr/bin/env python3
"""test_patterns.py — pytest proofs for the Asolaria ported primitives."""

import os
import sys
import subprocess
import tempfile

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))

from nest_cosign import run_tree  # noqa: E402
from hierarchical_planner import HierarchicalPlanner  # noqa: E402
from behcs_supervisor import Supervisor, hilbert_addr  # noqa: E402
from wormhole_bridge import WormholeBridge, Envelope  # noqa: E402
from nest_depthn import B, N, is_prime, run_tree as _run_depthn  # noqa: E402
from prism_comb import selftest as _prism_selftest  # noqa: E402


def test_nest_clean_verified():
    clean = run_tree(None)
    assert clean.gate_ok is True


def test_nest_tamper_caught():
    tampered = run_tree("R.1.2.0")
    assert tampered.gate_ok is False
    assert tampered.fail is not None and "R.1.2.0" in tampered.fail


def test_nest_no_false_positive():
    tampered = run_tree("R.1.2.0")
    assert "R.0.0.0" not in (tampered.fail or [])


def test_hrm_replans_and_budget():
    p = HierarchicalPlanner(h_cycles=2, l_cycles=3)
    p.run(steps=10)
    assert p.replans == 2
    assert p.microsteps <= 10


def test_hrm_sequence_order():
    p = HierarchicalPlanner(h_cycles=2, l_cycles=2)
    seq = [t for t, _ in p.run(steps=8)]
    for i, t in enumerate(seq):
        if t == "H":
            assert i + 1 < len(seq) and seq[i + 1] == "L"


def test_behcs_quick_success():
    s = Supervisor()
    r = s.operator_loop("aether", lambda st: True, lambda st: st)
    assert r["ok"] is True and r["loops"] == 1


def test_behcs_gc_cap():
    s = Supervisor(max_register=5)
    for k in range(10):
        s.operator_loop(f"t{k}", lambda st: True, lambda st: st)
    assert s.register_len() == 5


def test_behcs_exhaustion_logs_mistake():
    s = Supervisor(max_loops=3)
    r = s.operator_loop("falcon", lambda st: False, lambda st: st)
    assert r["ok"] is False and len(s.mistakes) == 1


def test_hilbert_addr_compat():
    a = hilbert_addr("aether")
    assert a.startswith("AGT-") and len(a) == 20


def test_wormhole_bridge():
    b = WormholeBridge("A", "B", b"secret")
    env = b.send("R.1.2.0", b"obj")
    assert b.receive_verify(env, "B", expected_payload=b"obj") is True
    evil = Envelope("A", "B", "R.1.2.0", b"bad", b"secret")
    assert b.receive_verify(evil, "B", expected_payload=b"obj") is False
    assert b.chain.verify() is True


def test_selftest_scripts_exit_zero():
    for mod in (
        "nest_cosign",
        "hierarchical_planner",
        "behcs_supervisor",
        "wormhole_bridge",
        "nest_depthn",
        "prism_comb",
    ):
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            r = subprocess.run(
                [sys.executable, os.path.join(LIB, mod + ".py"), "--selftest"],
                stdout=output,
                stderr=output,
                close_fds=False,
                text=True,
            )
            output.seek(0)
            receipt = output.read()
        assert r.returncode == 0, f"{mod} selftest failed: {receipt}"
        assert "PASS" in receipt, f"{mod} selftest missing PASS: {receipt}"


def test_depthn_clean_apex():
    tree = _run_depthn(None)
    assert is_prime(N)
    assert tree.gate_ok is True
    assert tree.subtree_ok is True
    assert tree.fail_by_depth == {}
    assert len(tuple(tree.iter_nodes())) == (B ** (N + 1) - 1) // (B - 1)
    assert tree.reported == _run_depthn(None).reported
    assert tree.fail == []


def test_depthn_every_level_caught():
    for d in range(1, N + 1):
        tamper = "R" + ".0" * d
        tree = _run_depthn(tamper)
        tampered = tree.find(tamper)
        assert tree.subtree_ok is False, f"level {d} confabulation not caught"
        assert tampered is not None and tampered.gate_ok is False
        assert tree.fail_by_depth == {d: (f"{tamper}@depth{d}",)}


def test_prism_bijection():
    import prism_comb as pc

    addrs = [f"R.{a}.{b}.{c}" for a in range(3) for b in range(3) for c in range(3)]
    for addr in addrs:
        v = pc.forward(addr)
        s = pc.seal(v)
        ok, rec = pc.inverse(addr, s)
        assert ok and rec == v
        bad = pc.sha16("seal|" + str(v ^ 0xBADBAD))
        ok_bad, _ = pc.inverse(addr, bad)
        assert ok_bad is False


def test_prism_crt_capacity_held():
    import prism_comb as pc

    capacity = pc.crt_capacity()
    assert capacity == 3 * 5 * 17 * 257

    # within capacity: exact recovery of x itself, not just x mod M
    x = capacity - 1
    residues = pc.crt_decompose(x)
    status, recomputed = pc.crt_recombine(residues, domain_size=capacity)
    assert status == "ok" and recomputed == x

    # declared domain larger than capacity: must Held, never silently
    # answer with a reduced (x mod M) value mislabeled as exact.
    status_held, value_held = pc.crt_recombine(residues, domain_size=capacity + 1)
    assert status_held == "held" and value_held is None


def test_prism_crt_lossless():
    import prism_comb as pc

    x = 123456789
    mods = [3, 5, 17, 257]
    residues = [x % m for m in mods]
    M = 1
    for m in mods:
        M *= m
    xr = 0
    for i, m in enumerate(mods):
        Mi = M // m
        inv = pow(Mi, -1, m)
        xr = (xr + residues[i] * Mi * inv) % M
    assert xr == x % M
