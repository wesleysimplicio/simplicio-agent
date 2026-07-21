#!/usr/bin/env python3
"""Evaluate GitHub job results fail-closed and write a reviewable receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.ci-quality-gate-receipt/v1"


def _result(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("result"), str):
        return value["result"]
    return None


def evaluate(needs: Any, *, allow_skipped: bool = True) -> dict[str, Any]:
    """Return PASS/FAIL/UNVERIFIED statuses without guessing on bad input."""
    if not isinstance(needs, dict) or not needs:
        return {"schema": SCHEMA, "status": "UNVERIFIED", "results": {},
                "reason": "missing or empty needs object"}
    results: dict[str, dict[str, str]] = {}
    has_failure = False
    has_unverified = False
    for name, value in sorted(needs.items()):
        raw = _result(value)
        if raw == "success":
            status = "PASS"
        elif raw == "skipped" and allow_skipped:
            status = "UNVERIFIED"
            has_unverified = True
        elif raw in {"failure", "cancelled", "timed_out", "action_required"}:
            status = "FAIL"
            has_failure = True
        else:
            status = "UNVERIFIED"
            has_unverified = True
        results[str(name)] = {"result": raw or "missing", "status": status}
    status = "FAIL" if has_failure else "UNVERIFIED" if has_unverified else "PASS"
    receipt: dict[str, Any] = {"schema": SCHEMA, "status": status, "results": results}
    if has_failure:
        receipt["reason"] = "one or more required jobs did not succeed"
    elif has_unverified:
        receipt["reason"] = "one or more jobs were skipped or had an unknown result"
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--needs-json", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        needs = json.loads(args.needs_json)
        receipt = evaluate(needs)
        exit_code = 0
    except json.JSONDecodeError as exc:
        receipt = evaluate(None)
        receipt["reason"] = f"invalid needs JSON: {exc.msg}"
        exit_code = 1
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, result in receipt["results"].items():
        print(f"{result['status']}| {name}: {result['result']}")
    print(f"{receipt['status']}| aggregate quality gate")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
