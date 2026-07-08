#!/usr/bin/env python3
"""behcs_supervisor.py — BEHCS-256 federated supervisor (deterministic port).

Port of asolaria-behcs-256/tools/behcs/behcs-agent-operator.js core loop.
Deterministic, no ADB/screenshots: the operator loop is modeled as a state
machine over a bounded NDJSON register with GC.

- Hilbert address = sha256_16 (compat asolaria_hbi_hbp::agt, "AGT-" + 16 hex).
- Register is append-only NDJSON; GC truncates to the last MAX lines.
- Operator loop: assess -> act -> verify, up to MAX_LOOPS; logs mistakes on fail.
"""
from __future__ import annotations
import hashlib
import json
import sys

MAX_LOOPS = 15
MAX_REGISTER = 200
MAX_MISTAKES = 100


def hilbert_addr(key: str) -> str:
    return "AGT-" + hashlib.sha256(key.encode()).hexdigest()[:16]


class Supervisor:
    def __init__(self, max_loops=MAX_LOOPS, max_register=MAX_REGISTER,
                 max_mistakes=MAX_MISTAKES):
        self.max_loops = max_loops
        self.max_register = max_register
        self.max_mistakes = max_mistakes
        self.register = []
        self.mistakes = []

    def _gc(self):
        if len(self.register) > self.max_register:
            self.register = self.register[-self.max_register:]
            return len(self.register)
        return 0

    def operator_loop(self, target: str, assess, act):
        """assess(state)->bool (correct?), act(state)->state. Models screenshot->check->fix->verify."""
        addr = hilbert_addr(target)
        state = {"target": target, "addr": addr}
        for i in range(self.max_loops):
            ok = assess(state)
            self.register.append(json.dumps({"loop": i, "target": target,
                                             "addr": addr, "ok": ok}))
            if ok:
                self._gc()
                return {"target": target, "addr": addr, "loops": i + 1, "ok": True}
            state = act(state)
        self.mistakes.append(json.dumps({"target": target, "addr": addr,
                                         "loops": self.max_loops, "ok": False}))
        if len(self.mistakes) > self.max_mistakes:
            self.mistakes = self.mistakes[-self.max_mistakes:]
        self._gc()
        return {"target": target, "addr": addr, "loops": self.max_loops, "ok": False}

    def register_len(self):
        return len(self.register)


def selftest():
    s1 = Supervisor()
    r1 = s1.operator_loop("aether", lambda st: True, lambda st: st)
    assert r1["ok"] is True and r1["loops"] == 1, f"expected quick success, got {r1}"

    s2 = Supervisor(max_register=5)
    for k in range(10):
        s2.operator_loop(f"t{k}", lambda st: True, lambda st: st)
    assert s2.register_len() == 5, f"GC must cap register at 5, got {s2.register_len()}"

    assert hilbert_addr("aether").startswith("AGT-") and len(hilbert_addr("aether")) == 20, \
        "hilbert addr must be AGT- + 16 hex"

    s3 = Supervisor(max_loops=3)
    r3 = s3.operator_loop("falcon", lambda st: False, lambda st: st)
    assert r3["ok"] is False and len(s3.mistakes) == 1, f"exhaustion must log mistake, got {r3}"

    print(f"BEHCS-SUPERVISOR|quick_ok={r1['ok']}|gc_cap={s2.register_len()}|"
          f"addr={hilbert_addr('aether')}|exhaust_mistakes={len(s3.mistakes)}|PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    s = Supervisor()
    print(json.dumps(s.operator_loop("aether", lambda st: True, lambda st: st)))
