#!/usr/bin/env python3
"""Canonical work-item lifecycle projector + transition validator.

Obeys the Simplicio Loop work-item protocol: every work-item lives in exactly
one canonical status and may only move along the allowed transition edges.
State is persisted as JSON in `.orchestrator/work-items/canonical-state.json`
(default) so it survives across agents/runs (replay idempotency).

Canonical statuses (protocol):
    intake -> mapping -> planning -> executing -> validating
            -> watching -> delivering -> done
Side states: blocked, quarantined (terminal-ish, re-enterable via retry).

Orca projection (read-only surface):
    intake|mapping      -> Todo
    planning           -> Planning
    executing          -> In progress
    validating|watching-> Validating
    delivering         -> In review
    done               -> Done
    blocked            -> Blocked
    quarantined        -> Quarantined

No status is ever marked done from model text or a passing command alone:
`done` requires evidence + watcher match + delivery receipt (recorded as
`receipts` on the work-item).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "simplicio-work-item-canonical/v1"

# Allowed directed edges (acyclic core + re-entry edges for failures).
TRANSITIONS: Dict[str, List[str]] = {
    "intake": ["mapping", "blocked"],
    "mapping": ["planning", "blocked", "intake"],
    "planning": ["executing", "blocked"],
    "executing": ["validating", "blocked", "quarantined"],
    "validating": ["watching", "executing", "blocked"],   # fail -> retry
    "watching": ["delivering", "executing", "blocked"],    # fail -> retry
    "delivering": ["done", "blocked"],
    "done": [],                                            # terminal
    "blocked": ["mapping", "planning", "executing", "intake"],
    "quarantined": ["executing", "blocked"],
}

ORCA_PROJECTION = {
    "intake": "Todo", "mapping": "Todo", "planning": "Planning",
    "executing": "In progress", "validating": "Validating", "watching": "Validating",
    "delivering": "In review", "done": "Done", "blocked": "Blocked",
    "quarantined": "Quarantined",
}

DEFAULT_STATE_PATH = Path(".orchestrator/work-items/canonical-state.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "schema": SCHEMA,
            "generated_at": now_iso(),
            "source": "github:wesleysimplicio/simplicio-runtime",
            "total_open": 0,
            "projection_rule": "intake|mapping->Todo, planning->Planning, executing->In progress, validating|watching->Validating, delivering->In review, done->Done, blocked->Blocked, quarantined->Quarantined",
            "work_items": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["generated_at"] = now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def find_wi(state: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    for wi in state["work_items"]:
        if wi["issue_number"] == n:
            return wi
    return None


def sync_github(state_path: Path, repo: str, limit: int = 500) -> Dict[str, Any]:
    """Reconcile canonical-state against live GitHub open issues."""
    out = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,state,labels,createdAt,updatedAt,url"],
        capture_output=True, text=True, cwd=repo,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {out.stderr}")
    issues = json.loads(out.stdout)
    state = load_state(state_path)
    existing = {wi["issue_number"]: wi for wi in state["work_items"]}
    work_items: List[Dict[str, Any]] = []
    for it in issues:
        num = it["number"]
        if num in existing:
            wi = existing[num]
            wi["title"] = it["title"]
            wi["labels"] = [l["name"] for l in it.get("labels", [])]
            wi["updated_at"] = it["updatedAt"]
            wi["github_state"] = it["state"]
        else:
            wi = {
                "id": f"WI-{num}",
                "issue_number": num,
                "title": it["title"],
                "github_state": it["state"],
                "labels": [l["name"] for l in it.get("labels", [])],
                "canonical_status": "intake",
                "orca_projection": "Todo",
                "created_at": it["createdAt"],
                "updated_at": it["updatedAt"],
                "github_url": it["url"],
                "transitions": ["intake"],
                "evidence": None,
                "receipts": [],
            }
        work_items.append(wi)
    state["work_items"] = work_items
    state["total_open"] = len(work_items)
    state["source"] = f"github:{repo}"
    save_state(state_path, state)
    return state


def cmd_list(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    items = state.get("work_items", [])
    if args.only:
        items = [w for w in items if w["canonical_status"] == args.only]
    for w in items:
        ev = " [E]" if w.get("evidence") else ""
        print(f"WI-{w['issue_number']:>4} | {w['canonical_status']:<10} -> "
              f"{w['orca_projection']:<11} | {w['title'][:50]}{ev}")
    print(f"\nMEASURED| total={len(items)} (schema={state.get('schema')})")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    wi = find_wi(state, args.number)
    if not wi:
        print(f"UNVERIFIED| WI-{args.number} not found", file=sys.stderr)
        return 1
    print(json.dumps(wi, indent=2))
    allowed = TRANSITIONS.get(wi["canonical_status"], [])
    print(f"\nMEASURED| valid transitions from '{wi['canonical_status']}': "
          f"{allowed or '(terminal)'}")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    wi = find_wi(state, args.number)
    if not wi:
        print(f"UNVERIFIED| WI-{args.number} not found", file=sys.stderr)
        return 1
    cur = wi["canonical_status"]
    target = args.to
    if target not in TRANSITIONS:
        print(f"UNVERIFIED| unknown status '{target}'; valid={list(TRANSITIONS)}",
              file=sys.stderr)
        return 2
    if target == cur:
        print(f"MEASURED| WI-{args.number} already '{cur}' (no-op, idempotent)")
        return 0
    if target not in TRANSITIONS[cur]:
        print(f"UNVERIFIED| illegal transition {cur} -> {target}; "
              f"allowed={TRANSITIONS[cur]}", file=sys.stderr)
        return 3
    receipt = {
        "event_id": f"{now_iso()}-{args.number}-{cur}-{target}",
        "from": cur, "to": target,
        "evidence_required": args.evidence is not None,
        "evidence": args.evidence,
        "delivery_receipt": args.delivery,
        "watcher_match": args.watcher,
        "actor": "simplicio-agent:cron",
        "replay_idempotent": True,
    }
    # Protocol: done requires evidence + watcher match + delivery receipt.
    if target == "done" and not (args.evidence and args.watcher and args.delivery):
        print("UNVERIFIED| 'done' requires --evidence AND --watcher AND --delivery "
              "(never from model text or a passing command alone)", file=sys.stderr)
        return 4
    wi["canonical_status"] = target
    wi["orca_projection"] = ORCA_PROJECTION[target]
    wi.setdefault("transitions", []).append(target)
    wi.setdefault("receipts", []).append(receipt)
    if args.evidence:
        wi["evidence"] = args.evidence
    save_state(args.state, state)  # persist canonical-state
    print(f"MEASURED| WI-{args.number}: {cur} -> {target} | receipt={receipt['event_id']}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    try:
        state = sync_github(args.state, args.repo, args.limit)
    except RuntimeError as e:
        print(f"UNVERIFIED| sync failed: {e}", file=sys.stderr)
        return 1
    print(f"MEASURED| synced {state['total_open']} open issues -> {args.state}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Canonical work-item lifecycle projector")
    p.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH,
                   help="canonical-state.json path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="project all work-items (Orca projection)")
    sp.add_argument("--only", help="filter by canonical_status")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="show one work-item + valid transitions")
    sp.add_argument("number", type=int)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("transition", help="validate + apply a transition")
    sp.add_argument("number", type=int)
    sp.add_argument("to")
    sp.add_argument("--evidence", help="evidence reference (file:line / command)")
    sp.add_argument("--watcher", action="store_true", help="watcher-gate matched")
    sp.add_argument("--delivery", help="delivery receipt (PR/merge id)")
    sp.set_defaults(func=cmd_transition)

    sp = sub.add_parser("sync", help="reconcile canonical-state with GitHub")
    sp.add_argument("--repo", default=".", help="git repo root")
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_sync)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
