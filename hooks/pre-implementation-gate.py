#!/usr/bin/env python3
"""#400 — Pre-Implementation Gate (deterministic, fail-closed).

Before any implementation (new file, new module, new PR) the agent MUST:

  1. Consult the neural database for the issue's domain.
  2. Load architecture skills by scope:
       - `senior-architect`            if design/architecture is involved
       - `asolaria-agent-table`       if agents/orchestration is involved
       - `real-agent-wave-engineering` if waves/multi-agent is involved
       - `wave-loop-tokio-integration` if Tokio/fan-out is involved
  3. Evaluate whether the DoD is achievable with existing infra; if not, declare
     a BLOCKER before opening any PR.

This hook verifies that a pre-implementation receipt exists and records those
steps. It is fail-closed: absence of evidence == gate failed. The receipt is a
small JSON file written by the agent (or the orchestrator) before dispatch:

    .orchestrator/pre-impl/<issue>.json
    {
      "issue": "400",
      "domain": "process-gate",
      "neural_queried": true,            # simplicio memory "<domain>" was run
      "neural_result": "UNVERIFIED| banco vazio" | "<summary>",
      "skills_loaded": ["senior-architect", "asolaria-agent-table"],
      "dod_achievable": true,            # false => must declare blocker, no PR
      "blocker": null | "<reason the DoD cannot be met with existing infra>",
      "agent": "<who performed the gate>"
    }

Usage:
    python3 hooks/pre-implementation-gate.py --issue 400 [--receipt .orchestrator/pre-impl/400.json]
    python3 hooks/pre-implementation-gate.py --self-test

Exit code 0 = gate satisfied; 1 = gate failed (do NOT implement / do NOT open PR).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / ".orchestrator"
DEFAULT_RECEIPT = ORCHESTRATOR / "pre-impl" / "{issue}.json"

# Skills the gate expects by scope, per issue #400.
SCOPE_SKILLS = {
    "design": "senior-architect",
    "architecture": "senior-architect",
    "agent": "asolaria-agent-table",
    "orchestration": "asolaria-agent-table",
    "wave": "real-agent-wave-engineering",
    "multi-agent": "real-agent-wave-engineering",
    "tokio": "wave-loop-tokio-integration",
    "fan-out": "wave-loop-tokio-integration",
}


def _load(receipt_path: Path) -> dict:
    if not receipt_path.exists():
        return {}
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def evaluate(receipt: dict, issue: str) -> tuple[bool, list[str]]:
    """Return (passed, reasons). Fail-closed: missing evidence fails."""
    reasons: list[str] = []
    if not isinstance(receipt, dict) or not receipt:
        return False, ["no pre-implementation receipt present (gate not run)"]

    # 1. neural query
    if not receipt.get("neural_queried"):
        reasons.append("neural database was NOT queried for this domain")

    # 2. scope skills loaded
    loaded = set(receipt.get("skills_loaded") or [])
    domain = " ".join(str(receipt.get("domain", "")).lower().split())
    expected = {SCOPE_SKILLS[k] for k in SCOPE_SKILLS if k in domain}
    missing = expected - loaded
    if missing:
        reasons.append("missing architecture skill(s) for domain scope: " + ", ".join(sorted(missing)))

    # 3. DoD achievability
    if receipt.get("dod_achievable") is False:
        blocker = receipt.get("blocker") or "unspecified"
        reasons.append(f"DoD declared NOT achievable with existing infra — BLOCKER: {blocker}")

    # 4. neural result must be explicit (never silent)
    if "neural_result" not in receipt:
        reasons.append("neural_result not recorded (must be explicit, even if 'UNVERIFIED| banco vazio')")

    passed = len(reasons) == 0
    return passed, reasons


def cmd_self_test() -> int:
    # A passing receipt.
    good = {
        "issue": "400", "domain": "process gate", "neural_queried": True,
        "neural_result": "UNVERIFIED| banco vazio", "skills_loaded": ["senior-architect"],
        "dod_achievable": True,
    }
    ok, why = evaluate(good, "400")
    assert ok, why

    # A failing receipt: skipped neural + missing skill.
    bad = {"issue": "183", "domain": "wave multi-agent tokio", "neural_queried": False,
           "skills_loaded": [], "dod_achievable": True}
    ok, why = evaluate(bad, "183")
    assert not ok and any("neural" in w for w in why), why
    assert any("real-agent-wave-engineering" in w for w in why), why

    # A blocker receipt must fail the gate.
    blocked = {"issue": "183", "domain": "wave multi-agent tokio", "neural_queried": True,
               "neural_result": "remote durable queue not present",
               "skills_loaded": ["senior-architect", "asolaria-agent-table",
                                 "real-agent-wave-engineering", "wave-loop-tokio-integration"],
               "dod_achievable": False, "blocker": "no remote durable queue + no real Codex/Claude workers"}
    ok, why = evaluate(blocked, "183")
    assert not ok and any("BLOCKER" in w for w in why), why

    print("pre-implementation-gate: self-test PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-Implementation Gate (#400)")
    parser.add_argument("--issue", required=False, default=None)
    parser.add_argument("--receipt", required=False, default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return cmd_self_test()

    if not args.issue:
        parser.error("--issue is required (or use --self-test)")
    receipt_path = Path(args.receipt) if args.receipt else Path(str(DEFAULT_RECEIPT).format(issue=args.issue))
    receipt = _load(receipt_path)
    passed, reasons = evaluate(receipt, args.issue)
    if passed:
        print(f"[pre-impl-gate] PASS issue={args.issue} ({receipt_path.name})")
        return 0
    print(f"[pre-impl-gate] BLOCKED issue={args.issue}")
    for r in reasons:
        print(f"  - {r}")
    print("[pre-impl-gate] Do NOT implement and do NOT open a PR until the gate passes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
