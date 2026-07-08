#!/usr/bin/env python3
"""hierarchical_planner.py — HRM two-level planner (deterministic port, no torch).

Port of HRM/models/hrm/hrm_act_v1.py outer loop (H_cycles / L_cycles) without
the neural net. The structure is preserved:
  - High-level (SLOW) planner re-plans every H_cycles low-level steps.
  - Low-level (FAST) planner executes L_cycles micro-steps between high re-plans.
  - Carry state z_H / z_L is propagated between levels (here: opaque strings/dicts).

This is a pure control-flow primitive. Swap the `plan`/`act` callbacks for real
tools; the halting/two-level discipline is what HRM contributes.
"""
from __future__ import annotations
import sys


class HierarchicalPlanner:
    def __init__(self, h_cycles: int = 2, l_cycles: int = 3,
                 high_plan=None, low_act=None):
        self.H = h_cycles
        self.L = l_cycles
        self._high = high_plan or (lambda z_h, z_l: f"H({z_h},{z_l})")
        self._low = low_act or (lambda z_l, z_h: f"L({z_l},{z_h})")
        self.replans = 0
        self.microsteps = 0

    def run(self, steps: int, z_h: str = "h0", z_l: str = "l0"):
        log = []
        for _h in range(self.H):
            z_h = self._high(z_h, z_l)          # SLOW re-plan
            self.replans += 1
            log.append(("H", z_h))
            for _l in range(self.L):
                if self.microsteps >= steps:
                    return log
                z_l = self._low(z_l, z_h)        # FAST micro-step
                self.microsteps += 1
                log.append(("L", z_l))
        return log


def selftest():
    p = HierarchicalPlanner(h_cycles=2, l_cycles=3)
    log = p.run(steps=10)
    assert p.replans == 2, f"expected 2 high replans, got {p.replans}"
    assert p.microsteps <= 10, f"microsteps must respect step budget, got {p.microsteps}"
    seq = [t for t, _ in log]
    assert all(seq[i] == "L" or (i + 1 < len(seq) and seq[i + 1] == "L")
               for i, t in enumerate(seq) if t == "H"), "H must lead L blocks"
    print(f"HRM-PLANNER|replans={p.replans}|microsteps={p.microsteps}|"
          f"seq={' '.join(seq)}|PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    p = HierarchicalPlanner()
    for t, v in p.run(steps=6):
        print(t, v)
