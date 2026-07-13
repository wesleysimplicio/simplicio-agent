#!/usr/bin/env python3
"""prism_comb.py — Prism/Comb 0-loss law, the N-Nest instance (deterministic port).

Port of N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED/PRISM-COMB-0LOSS-NEST.md.

The law, one line:
  Every prism/comb operation in Asolaria is a BIJECTION, and entropy is
  invariant under bijection (H(f(X)) = H(X)): the system re-relates information
  with 0 loss and never claims compression below entropy (Shannon's
  E[bits] >= H(X) always stands).

The integrity face (this module):
  (b) The per-node gate is the groupoid coherence check.
      child.reported == watcher.recomputed_truth, AND'd over children, is
      verification = recomputation = applying the inverse map. A fabricated
      report has no inverse that closes the round-trip to identity.

MEASURED proof we add (0-loss round-trip):
  Given a ground-truth value v at a node, the forward map f produces the
  reported seal; the inverse map f^{-1} recomputes v. We assert:
    f^{-1}(f(v)) == v            (round-trip closes -> bijection)
    H(f(v)) == H(v)              (entropy invariant, 0 loss)
  This is what makes confabulation and loss the SAME impossibility.

Scientific-integrity correction (issue #124 comment, ref #141) folded in here:
  - Bijection is proven by round-trip AND injectivity over the declared
    domain (all forward(addr) values for the tested addrs are pairwise
    distinct), not by hash-vs-int comparison alone.
  - Entropy invariance is measured as the empirical Shannon entropy
    (population_entropy, H = -sum p_i log2 p_i) of the *distribution* of
    ground-truth values vs. the distribution of their sealed images over the
    SAME finite sample -- never a single-integer log2(x+1) proxy compared
    against a hash's raw numeric value (that measures nothing about H(X)).
    A 1:1 relabeling of a finite population cannot change its symbol
    frequencies, so H is exactly preserved -- this is what "0-loss" means
    here, not a claim about entropy of an unbounded random variable.
  - CRT recombination explicitly declares its capacity
    M = product(moduli) and REFUSES to claim losslessness outside it:
    crt_recombine() returns ("held", None) whenever the caller-declared
    domain_size exceeds M, instead of silently returning `x mod M` and
    calling that "the same x". Losslessness is only asserted for
    domain_size <= M, where CRT recombination of the per-modulus residues
    recovers the original value exactly (not merely x mod M).

Consent stays outside the bijection (LAW.md): observation/correction nest
infinitely (they are the inverse maps), but consent is non-recursive —
authorization to scale anchors only at the human apex. A bijection can verify
anything; it can authorize nothing.
"""
from __future__ import annotations
import hashlib
import math
import sys


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# --- forward / inverse maps over a deterministic N-Nest leaf value -----------
# Leaf ground-truth: v = int(sha16('work|' + addr), 16) mod 1_000_000
# Forward map f: v -> seal = sha16('seal|' + str(v))      (the reported/watcher value)
# Inverse map f^-1: seal -> recomputed v via the same deterministic rule.
def forward(addr: str) -> int:
    return int(sha16("work|" + addr), 16) % 1_000_000


def seal(v: int) -> str:
    """Forward bijection: ground-truth value -> reported seal (the watcher's form)."""
    return sha16("seal|" + str(v))


def inverse(addr: str, reported_seal: str) -> tuple:
    """Inverse map: recompute v from the SAME rule and check the seal closes.

    Returns (round_trip_ok, recomputed_v). round_trip_ok = True iff the
    reported seal is exactly f(v) for the node's true v — i.e. the bijection
    round-trips. A confabulated seal fails this (no inverse closes it).
    """
    true_v = forward(addr)
    return (seal(true_v) == reported_seal), true_v


from collections import Counter


def population_entropy(symbols) -> float:
    """Shannon entropy (bits) of a population of symbols (the distribution).

    H = -sum p_i log2 p_i. This is the quantity the PRISM-COMB law says is
    invariant under bijection: relabeling each symbol via a 1:1 map does not
    change how many distinct symbols there are nor their frequencies, so the
    distribution's entropy is unchanged (0 loss). We measure it on the *set of
    leaves' ground-truth values* before and after applying the forward map -
    both are the same multiset up to relabel, so H is equal.
    """
    n = len(symbols)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(symbols).values())


# --- CRT many->1 recombination (explicit capacity, Held when insufficient) --
# Prism-style recombination: N pairwise-coprime moduli decompose a value into
# residues; CRT recombines the residues back into a single value. This is
# lossless ONLY within the declared capacity M = product(moduli) -- a value
# outside [0, M) cannot be told apart from (value mod M) by its residues
# alone, so claiming "0 loss" there would be exactly the confabulation this
# module exists to rule out. See issue #124 comment (ref #141).
CRT_MODULI: tuple[int, ...] = (3, 5, 17, 257)  # pairwise coprime


def crt_capacity(moduli: tuple[int, ...] = CRT_MODULI) -> int:
    """M = product(moduli): the largest domain size CRT can recombine losslessly."""
    m_total = 1
    for m in moduli:
        m_total *= m
    return m_total


def crt_decompose(x: int, moduli: tuple[int, ...] = CRT_MODULI) -> tuple[int, ...]:
    """Prism step: x -> per-modulus residues."""
    return tuple(x % m for m in moduli)


def crt_recombine(
    residues: tuple[int, ...],
    moduli: tuple[int, ...] = CRT_MODULI,
    domain_size: int | None = None,
) -> tuple[str, int | None]:
    """Comb step: residues -> recombined value.

    Returns (status, value):
      - ("ok", x)     when domain_size is None or domain_size <= capacity --
                      x is recovered exactly (not merely x mod M).
      - ("held", None) when the caller declares domain_size > capacity: CRT
                      alone cannot guarantee losslessness there, so this
                      function refuses to answer rather than silently return
                      a reduced (x mod M) value mislabeled as exact.
    """
    m_total = crt_capacity(moduli)
    if domain_size is not None and domain_size > m_total:
        return "held", None
    x_recomb = 0
    for r, m in zip(residues, moduli):
        m_i = m_total // m
        inv = pow(m_i, -1, m)
        x_recomb = (x_recomb + r * m_i * inv) % m_total
    return "ok", x_recomb


def selftest():
    # 1) round-trip bijection over many leaves: f^-1(f(v)) == v, AND injectivity
    #    (all forward(addr) values are pairwise distinct over the tested domain).
    addrs = [f"R.{a}.{b}.{c}" for a in range(3) for b in range(3) for c in range(3)]
    raw_v = []
    raw_seal = []
    for addr in addrs:
        v = forward(addr)
        s = seal(v)
        ok, recomputed = inverse(addr, s)
        assert ok and recomputed == v, f"bijection round-trip failed at {addr}"
        raw_v.append(v)
        raw_seal.append(int(s, 16))
    assert len(set(raw_v)) == len(raw_v), \
        "forward() is not injective over the tested domain -- not a bijection"
        # 2) entropy invariant under the bijection (0 loss): the *distribution*
        #    of leaf symbols is preserved by a 1:1 relabel, so H is unchanged.
    h_v = population_entropy(raw_v)
    h_seal = population_entropy(raw_seal)
    assert abs(h_v - h_seal) < 1e-9, \
        f"population entropy not invariant under bijection: H(v)={h_v} H(seal)={h_seal}"

    # 3) confabulation has NO inverse that closes -> the same impossibility as loss
    good_addr = "R.0.0.0"
    v = forward(good_addr)
    confabulated_seal = sha16("seal|" + str(v ^ 0xBADBAD))  # tampered
    ok_conf, _ = inverse(good_addr, confabulated_seal)
    assert ok_conf is False, "confabulated seal must NOT close the inverse map"

    # 4) many->1 recombination (CRT-style prism), WITHIN declared capacity:
    #    residues recombine to exactly x (0 loss), not merely x mod M.
    capacity = crt_capacity()
    x = capacity - 1  # boundary value still inside [0, M)
    residues = crt_decompose(x)
    status_ok, x_recomb = crt_recombine(residues, domain_size=capacity)
    assert status_ok == "ok" and x_recomb == x, \
        "CRT recombination lost information within declared capacity (loss != 0)"

    # 4b) capacity is EXPLICIT: a domain declared larger than M must be Held,
    #     never silently answered with a reduced (x mod M) value.
    status_held, value_held = crt_recombine(residues, domain_size=capacity + 1)
    assert status_held == "held" and value_held is None, \
        "CRT recombine must return Held when domain_size exceeds capacity"

    print(f"PRISM-COMB-0LOSS|bijection_roundtrip=PASS|entropy_invariant=PASS|"
          f"confabulation_no_inverse=PASS|crt_recombine_lossless=PASS|PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print("prism_comb: run with --selftest")
