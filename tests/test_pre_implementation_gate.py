"""#400 — Pre-Implementation Gate hook tests.

Verifies the fail-closed gate in hooks/pre-implementation-gate.py:
  - a missing receipt blocks;
  - a receipt that skipped the neural query blocks;
  - a receipt missing the scope skill blocks;
  - a receipt declaring DoD-not-achievable blocks (must declare blocker, no PR);
  - a well-formed receipt (neural queried, skills loaded, DoD achievable, explicit
    neural_result) passes;
  - the committed #400 example receipt passes the gate for real.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# hooks/ is not a package; load the module by file path so the test is hermetic.
_HOOK = REPO / "hooks" / "pre-implementation-gate.py"
_spec = importlib.util.spec_from_file_location("pre_implementation_gate", _HOOK)
pre_implementation_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pre_implementation_gate)
evaluate = pre_implementation_gate.evaluate


def test_missing_receipt_blocks():
    ok, why = evaluate({}, "999")
    assert not ok
    assert any("no pre-implementation receipt" in w for w in why)


def test_skipped_neural_query_blocks():
    ok, why = evaluate({"issue": "1", "neural_queried": False,
                        "skills_loaded": [], "dod_achievable": True}, "1")
    assert not ok
    assert any("neural" in w for w in why)


def test_missing_scope_skill_blocks():
    # domain mentions wave + multi-agent + tokio => expects 3 architecture skills.
    ok, why = evaluate({"issue": "2", "domain": "wave multi-agent tokio fan-out",
                        "neural_queried": True, "neural_result": "UNVERIFIED| banco vazio",
                        "skills_loaded": ["senior-architect"], "dod_achievable": True}, "2")
    assert not ok
    assert any("real-agent-wave-engineering" in w for w in why)
    assert any("wave-loop-tokio-integration" in w for w in why)


def test_dod_not_achievable_blocks_with_blocke_r():
    ok, why = evaluate({"issue": "3", "domain": "wave multi-agent tokio",
                        "neural_queried": True, "neural_result": "remote queue missing",
                        "skills_loaded": ["senior-architect", "asolaria-agent-table",
                                          "real-agent-wave-engineering", "wave-loop-tokio-integration"],
                        "dod_achievable": False, "blocker": "no remote durable queue"}, "3")
    assert not ok
    assert any("BLOCKER" in w for w in why)


def test_well_formed_receipt_passes():
    ok, why = evaluate({"issue": "4", "domain": "process gate",
                        "neural_queried": True, "neural_result": "UNVERIFIED| banco vazio",
                        "skills_loaded": ["senior-architect"], "dod_achievable": True}, "4")
    assert ok, why


def test_committed_400_receipt_passes():
    receipt_path = REPO / ".orchestrator" / "pre-impl" / "400.json"
    import json
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    ok, why = evaluate(receipt, "400")
    assert ok, why


def test_self_test_runs_clean():
    import subprocess
    result = subprocess.run(["python3", "hooks/pre-implementation-gate.py", "--self-test"],
                            cwd=str(REPO), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "self-test PASS" in result.stdout
