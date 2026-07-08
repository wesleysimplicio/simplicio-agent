#!/usr/bin/env python3
"""test_patterns.py — pytest proofs for the Asolaria ported primitives."""
import os
import sys
import subprocess

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))

from nest_cosign import run_tree  # noqa: E402
from hierarchical_planner import HierarchicalPlanner  # noqa: E402
from behcs_supervisor import Supervisor, hilbert_addr  # noqa: E402
from wormhole_bridge import WormholeBridge, Envelope  # noqa: E402


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
    for mod in ("nest_cosign", "hierarchical_planner", "behcs_supervisor", "wormhole_bridge"):
        r = subprocess.run([sys.executable, os.path.join(LIB, mod + ".py"), "--selftest"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{mod} selftest failed: {r.stderr}"
        assert "PASS" in r.stdout, f"{mod} selftest missing PASS: {r.stdout}"
