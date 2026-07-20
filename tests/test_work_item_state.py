"""Unit tests for the canonical work-item lifecycle projector/validator.

Exercises the Simplicio Loop work-item protocol edges:
- allowed transitions succeed, illegal ones fail
- `done` is blocked without evidence + watcher + delivery
- full chain intake->...->done succeeds and persists a receipt
- idempotent re-application of the same status is a no-op (exit 0)
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "work_item_state.py"


def _run(*args, state):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--state", str(state), *args],
        capture_output=True, text=True,
    )


def _make_state(state_path: Path, n: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "simplicio-work-item-canonical/v1",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source": "github:test",
        "total_open": 1,
        "projection_rule": "x",
        "work_items": [{
            "id": f"WI-{n}", "issue_number": n, "title": "test",
            "github_state": "OPEN", "labels": [], "canonical_status": "intake",
            "orca_projection": "Todo", "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z", "github_url": "x",
            "transitions": ["intake"], "evidence": None, "receipts": [],
        }],
    }
    state_path.write_text(json.dumps(state))


def test_illegal_transition_rejected(tmp_path):
    st = tmp_path / "cs.json"
    _make_state(st, 1)
    r = _run("transition", "1", "done", state=st)
    assert r.returncode == 3, r.stderr
    assert "illegal transition" in r.stderr


def test_done_blocked_without_evidence(tmp_path):
    st = tmp_path / "cs.json"
    _make_state(st, 2)
    # walk to delivering, then attempt done with nothing
    for t in ("mapping", "planning", "executing", "validating", "watching", "delivering"):
        _run("transition", "2", t, "--evidence", f"e:{t}", "--watcher",
             "--delivery", "PR#2", state=st)
    r = _run("transition", "2", "done", state=st)
    assert r.returncode == 4, r.stderr
    assert "done" in r.stderr and "evidence" in r.stderr


def test_full_chain_succeeds(tmp_path):
    st = tmp_path / "cs.json"
    _make_state(st, 3)
    chain = ("mapping", "planning", "executing", "validating",
             "watching", "delivering", "done")
    for t in chain:
        r = _run("transition", "3", t, "--evidence", f"e:{t}", "--watcher",
                 "--delivery", "PR#3", state=st)
        assert r.returncode == 0, (t, r.stderr)
    data = json.loads(st.read_text())
    wi = data["work_items"][0]
    assert wi["canonical_status"] == "done"
    assert wi["orca_projection"] == "Done"
    assert len(wi["receipts"]) == len(chain)
    assert all(rc["replay_idempotent"] for rc in wi["receipts"])


def test_idempotent_same_status(tmp_path):
    st = tmp_path / "cs.json"
    _make_state(st, 4)
    _run("transition", "4", "mapping", state=st)
    r = _run("transition", "4", "mapping", state=st)
    assert r.returncode == 0
    assert "no-op" in r.stdout


def test_show_lists_valid_transitions(tmp_path):
    st = tmp_path / "cs.json"
    _make_state(st, 5)
    r = _run("show", "5", state=st)
    assert r.returncode == 0
    assert "mapping" in r.stdout and "blocked" in r.stdout
