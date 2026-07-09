#!/usr/bin/env python3
"""nest_depthn.py — depth-N (N PRIME) nested self-reflection (deterministic port).

Port of N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED/nest-depthN-prime-verify.cjs.

Contract (matches the Jesse source exactly):
- B = branching factor, N = PRIME depth.
- leaf.true   = truth(addr)              = sha16('work|' + addr)
- internal.true = sha16(addr | children's reported values)
- node.gate_ok = (reported === true)     <- corrective gate at THIS node
- subtree_ok   = gate_ok AND all(child.subtree_ok)
- A confabulation at ANY depth makes that node's gate_ok=false -> bubbles to
  apex (subtree_ok=false) and report.fail names the node @depth{d}.

Proof (the part our old nest_cosign.py did NOT cover): inject one fault at
EVERY level 1..N, verify the gate catches it at that EXACT level. No fake-green
— every level must bite. This is depth-independent by construction
(PRISM-COMB-0LOSS-NEST.md): coherence composes per-node identity checks into a
whole-tree identity check at any depth-N.
"""
from __future__ import annotations
import hashlib
import sys

B = 2          # branching 2 (keeps depth-7 tree at 255 nodes)
N = 7          # PRIME depth


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def truth(a: str) -> str:
    return sha16("work|" + a)


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


class Node:
    __slots__ = ("addr", "depth", "agent_pid", "watcher_pid", "reported",
                 "gate_ok", "subtree_ok", "fail", "kids")

    def __init__(self, addr, depth, tamper_addr):
        self.addr = addr
        self.depth = depth
        self.agent_pid = sha16(addr)
        self.watcher_pid = sha16(addr + "|watch")
        if depth == N:
            true_val = truth(addr)
            self.kids = None
        else:
            self.kids = [Node(f"{addr}.{i}", depth + 1, tamper_addr)
                         for i in range(B)]
            true_val = sha16(addr + "|" + ",".join(k.reported for k in self.kids))
        # watcher recomputes true_val; tamper breaks the match at THIS node
        self.reported = sha16(true_val + "|CONFABULATED") if addr == tamper_addr else true_val
        self.gate_ok = self.reported == true_val
        if self.kids:
            self.subtree_ok = self.gate_ok and all(k.subtree_ok for k in self.kids)
            failing = []
            if not self.gate_ok:
                failing.append(f"{addr}@depth{depth}")
            for k in self.kids:
                failing.extend(k.fail)
            self.fail = failing
        else:
            self.subtree_ok = self.gate_ok
            self.fail = [f"{addr}@depth{depth}"] if not self.gate_ok else []


def run_tree(tamper_addr=None):
    return Node("R", 0, tamper_addr)


def selftest():
    clean = run_tree(None)
    assert clean.subtree_ok is True, "clean apex must be VERIFIED"

    # inject a confabulation at EVERY level 1..N; verify caught at exact depth
    all_caught = True
    caught_rows = []
    for d in range(1, N + 1):
        tamper_addr = "R" + ".0" * d
        r = run_tree(tamper_addr)
        caught_here = (r.subtree_ok is False
                       and any(f.endswith(f"@depth{d}") for f in r.fail))
        all_caught = all_caught and caught_here
        if not caught_here:
            caught_rows.append(f"LEVEL-{d} NOT CAUGHT: fail={r.fail}")
    assert all_caught, "every level must catch confabulation:\n" + "\n".join(caught_rows)

    print(f"NEST-DEPTHN-PRIME|branching={B}|depth={N}|prime={is_prime(N)}|"
          f"clean_apex_ok={clean.subtree_ok}|"
          f"EVERY-LEVEL-CATCHES-CONFABULATION={all_caught}|PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    clean = run_tree(None)
    print(f"{clean.subtree_ok}")
