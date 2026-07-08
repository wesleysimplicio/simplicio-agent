#!/usr/bin/env python3
"""nest_cosign.py — N-Nest cosign + corrective gate (deterministic port).

Port of N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED/nest-depth3-verify.cjs.

Each node = agent PID + watcher PID (the self-reflect agent that recomputes the
node's ground-truth). A parent authorizes a child only if the child's REPORTED
output == the watcher's independently-recomputed ground truth. Consent (clean
roll-up to apex) fires only if EVERY level passes. Tamper test: inject a
confabulation 3 levels deep; the gate MUST catch it (apex UNVERIFIED, names path).

Hashing matches asolaria_hbi_hbp: sha256 -> first 16 hex chars per node id.
A cosign receipt chain (hash-chained, tamper-evident) is appended per authorized node.
"""
from __future__ import annotations
import hashlib
import json
import sys

B = 3          # branching factor
DEPTH = 3      # tree depth -> B^DEPTH leaves (the B^DEPTH wave)


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def truth(seed: str) -> int:
    """Ground-truth value of a node's work (deterministic)."""
    return int(sha16("work|" + seed), 16) % 1_000_000


class Node:
    __slots__ = ("addr", "agent_pid", "watcher_pid", "reported", "value", "gate_ok",
                 "leaf", "rollup", "kids", "fail")

    def __init__(self, addr, depth, tamper_path):
        self.addr = addr
        self.agent_pid = sha16(addr)
        self.watcher_pid = sha16(addr + "|watch")
        if depth == DEPTH:
            real = truth(addr)
            self.value = (real ^ 0xBADBAD) if addr == tamper_path else real
            self.reported = hex(self.value)  # string form for parent roll-up
            watcher_truth = truth(addr)
            self.gate_ok = self.value == watcher_truth
            self.leaf = True
            self.rollup = None
            self.kids = None
            self.fail = None if self.gate_ok else [addr]
        else:
            kids = [Node(f"{addr}.{i}", depth + 1, tamper_path) for i in range(B)]
            self.kids = kids
            all_ok = all(k.gate_ok for k in kids)
            self.value = None
            self.reported = sha16(addr + "|" + ",".join(k.reported for k in kids))
            self.gate_ok = all_ok
            self.leaf = False
            self.rollup = self.reported
            failing = [p for k in kids for p in (k.fail or [])]
            self.fail = failing if failing else None


def run_tree(tamper_path=None):
    return Node("R", 0, tamper_path)


def selftest():
    clean = run_tree(None)
    tampered = run_tree("R.1.2.0")  # confabulate one leaf, depth-3
    assert clean.gate_ok is True, "clean apex must be VERIFIED"
    assert tampered.gate_ok is False, "tampered apex must be UNVERIFIED"
    assert tampered.fail is not None and "R.1.2.0" in tampered.fail, \
        f"gate must name tampered path, got {tampered.fail}"
    chain = []
    prev = "0" * 64
    stack = [clean]
    while stack:
        n = stack.pop()
        if n.gate_ok:
            body = f"COSIGN|addr={n.addr}|agent={n.agent_pid}|watch={n.watcher_pid}"
            eh = sha16(body + "|prev=" + prev)
            chain.append(f"{body}|prev={prev}|eh={eh}")
            prev = eh
            if n.kids:
                stack.extend(n.kids)
    prev = "0" * 64
    for r in chain:
        body = r.split("|prev=")[0]
        claimed = r.split("eh=")[1]
        assert sha16(body + "|prev=" + prev) == claimed, "cosign chain broken"
        prev = claimed
    print("NEST-COSIGN|clean_apex=VERIFIED|tampered_apex=UNVERIFIED|"
          f"caught_path={'R.1.2.0'}|cosign_links={len(chain)}|PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    clean = run_tree(None)
    print(json.dumps({"apex_gate_ok": clean.gate_ok, "apex_rollup": clean.rollup}))
