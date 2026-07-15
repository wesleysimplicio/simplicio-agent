#!/usr/bin/env python3
"""nest_depthn.py — depth-N (N PRIME) nested self-reflection (deterministic port).

Parity with skills/asolaria-patterns/lib/nest_depthn.py (issue #123).

This is an original Simplicio implementation of the N-Nest behavior contract;
it does not copy external source code.  The tree is intentionally small and
fully inspectable so each corrective gate can be tested independently.

Contract for issue #123:
- B = branching factor, N = PRIME depth.
- leaf.true   = truth(addr)              = sha16('work|' + addr)
- internal.true = sha16(addr | children's reported values)
- node.gate_ok = (reported == true)      <- corrective gate at THIS node
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

B = 2  # branching 2 (keeps depth-7 tree at 255 nodes)
N = 7  # PRIME depth


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
    """One node in the deterministic binary hash tree.

    ``true_hash`` is the watcher's recomputation and ``reported`` is the
    agent's claim.  Keeping both values makes a local gate observable instead
    of treating an apex failure as the only proof.  ``fail_by_depth`` contains
    only local gate failures and is rolled up without losing their depth.
    """

    __slots__ = (
        "addr",
        "depth",
        "agent_pid",
        "watcher_pid",
        "true_hash",
        "reported",
        "gate_ok",
        "subtree_ok",
        "fail",
        "fail_by_depth",
        "kids",
    )

    def __init__(self, addr, depth, tamper_addr):
        self.addr = addr
        self.depth = depth
        self.agent_pid = sha16(addr)
        self.watcher_pid = sha16(addr + "|watch")
        if depth == N:
            true_hash = truth(addr)
            self.kids = None
        else:
            self.kids = [Node(f"{addr}.{i}", depth + 1, tamper_addr) for i in range(B)]
            true_hash = sha16(addr + "|" + ",".join(k.reported for k in self.kids))
        # watcher recomputes true_val; tamper breaks the match at THIS node
        self.true_hash = true_hash
        self.reported = (
            sha16(true_hash + "|CONFABULATED") if addr == tamper_addr else true_hash
        )
        self.gate_ok = self.reported == self.true_hash
        if self.kids:
            self.subtree_ok = self.gate_ok and all(k.subtree_ok for k in self.kids)
            failures = {
                level: list(paths)
                for child in self.kids
                for level, paths in child.fail_by_depth.items()
            }
            if not self.gate_ok:
                failures.setdefault(depth, []).append(f"{addr}@depth{depth}")
        else:
            self.subtree_ok = self.gate_ok
            failures = {depth: [f"{addr}@depth{depth}"]} if not self.gate_ok else {}
        self.fail_by_depth = {
            level: tuple(paths) for level, paths in sorted(failures.items())
        }
        self.fail = [path for paths in self.fail_by_depth.values() for path in paths]

    @property
    def true(self) -> str:
        """Compatibility alias for the watcher's true hash."""

        return self.true_hash

    @property
    def hash(self) -> str:
        """The hash reported by this node (the value committed upward)."""

        return self.reported

    def find(self, addr: str) -> "Node | None":
        """Return the node at ``addr`` or ``None`` when it is not in the tree."""

        if self.addr == addr:
            return self
        return next(
            (found for kid in self.kids or () if (found := kid.find(addr)) is not None),
            None,
        )

    def iter_nodes(self):
        """Yield this node and descendants in deterministic address order."""

        yield self
        for kid in self.kids or ():
            yield from kid.iter_nodes()


def run_tree(tamper_addr=None):
    return Node("R", 0, tamper_addr)


def hash_tree(tamper_addr=None):
    """Build the deterministic hash tree; alias kept explicit for callers."""

    return run_tree(tamper_addr)


def selftest():
    assert is_prime(N), f"N must be prime, got {N}"
    clean = run_tree(None)
    assert clean.gate_ok is True, "clean apex gate must be VERIFIED"
    assert clean.subtree_ok is True, "clean apex subtree must be VERIFIED"
    assert clean.fail_by_depth == {}, "clean tree must have no depth failures"
    assert len(tuple(clean.iter_nodes())) == (B ** (N + 1) - 1) // (B - 1)

    # inject a confabulation at EVERY level 1..N; verify caught at exact depth
    all_caught = True
    caught_rows = []
    for d in range(1, N + 1):
        tamper_addr = "R" + ".0" * d
        r = run_tree(tamper_addr)
        tampered = r.find(tamper_addr)
        caught_here = (
            r.subtree_ok is False
            and tampered is not None
            and tampered.gate_ok is False
            and set(r.fail_by_depth) == {d}
            and r.fail_by_depth[d] == (f"{tamper_addr}@depth{d}",)
        )
        all_caught = all_caught and caught_here
        if not caught_here:
            caught_rows.append(f"LEVEL-{d} NOT CAUGHT: fail_by_depth={r.fail_by_depth}")
    assert all_caught, "every level must catch confabulation:\n" + "\n".join(
        caught_rows
    )

    print(
        f"NEST-DEPTHN-PRIME|branching={B}|depth={N}|prime={is_prime(N)}|"
        f"clean_apex_ok={clean.subtree_ok}|"
        f"EVERY-LEVEL-CATCHES-CONFABULATION={all_caught}|PASS"
    )
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    clean = run_tree(None)
    print(f"{clean.subtree_ok}")
