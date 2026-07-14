#!/usr/bin/env python3
"""Emit a bounded SOURCE -> LOADED -> CALLED prompt-microkernel receipt.

This checker deliberately stops at the boundary it executes.  Packaging,
default activation, and product end-to-end behavior remain explicitly
unverified instead of being inferred from a successful import or call.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "simplicio.perf-integration-receipt/v1"
SOURCE_PATH = "agent/prompt_microkernel.py"


def _unverified() -> dict[str, str]:
    return {
        "status": "unknown",
        "claim": "UNVERIFIED",
        "reason": "not measured by this bounded receipt",
    }


def collect_receipt(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Execute the three measured stages and return deterministic evidence."""

    root = repo_root.resolve()
    source = root / SOURCE_PATH
    source_exists = source.is_file()
    source_sha256 = (
        hashlib.sha256(source.read_bytes()).hexdigest() if source_exists else ""
    )
    stages: dict[str, dict[str, Any]] = {
        "SOURCE": {
            "status": "pass" if source_exists else "fail",
            "claim": "MEASURED",
            "evidence": {
                "path": SOURCE_PATH,
                "sha256": source_sha256,
            },
        }
    }

    old_path = list(sys.path)
    module = None
    try:
        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        module = importlib.import_module("agent.prompt_microkernel")
    except Exception as exc:  # pragma: no cover - defensive CLI receipt
        load_error = type(exc).__name__
    else:
        load_error = ""
    finally:
        sys.path[:] = old_path

    loaded_from_source = bool(
        module is not None
        and source_exists
        and Path(module.__file__).resolve() == source.resolve()
    )
    stages["LOADED"] = {
        "status": "pass" if loaded_from_source else "fail",
        "claim": "MEASURED",
        "evidence": {
            "module": "agent.prompt_microkernel",
            "source_match": loaded_from_source,
            "error": load_error,
        },
    }

    called = False
    call_evidence: dict[str, Any] = {
        "symbol": "CapabilityBroker.expand_with_receipt",
        "capability_id": "act",
    }
    if loaded_from_source and module is not None:
        try:
            broker = module.CapabilityBroker([
                {
                    "type": "function",
                    "function": {"name": "act", "description": "receipt probe"},
                }
            ])
            schema, expansion = broker.expand_with_receipt("act")
            repeated = broker.expand_with_receipt("act")[1]
            called = bool(
                schema["function"]["name"] == "act"
                and expansion.capability_id == "act"
                and expansion == repeated
                and expansion.schema_sha256
            )
            call_evidence.update({
                "schema_sha256": expansion.schema_sha256,
                "cache_stable": expansion.cache_stable,
            })
        except Exception as exc:  # pragma: no cover - defensive CLI receipt
            call_evidence["error"] = type(exc).__name__
    stages["CALLED"] = {
        "status": "pass" if called else "fail",
        "claim": "MEASURED",
        "evidence": call_evidence,
    }

    for stage in ("PACKAGED", "DEFAULT", "E2E"):
        stages[stage] = _unverified()

    return {
        "schema": SCHEMA,
        "optimization": "prompt-microkernel",
        "scope": ["SOURCE", "LOADED", "CALLED"],
        "ok": all(
            stages[stage]["status"] == "pass"
            for stage in ("SOURCE", "LOADED", "CALLED")
        ),
        "stages": stages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    receipt = collect_receipt(args.repo)
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        for stage in receipt["scope"]:
            result = receipt["stages"][stage]
            print(f"{result['claim']}| {stage}={result['status']}")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
