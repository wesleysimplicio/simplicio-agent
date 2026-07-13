#!/usr/bin/env python3
"""A/B/C benchmark: token estimators for the pre-flight budget path (issue #111).

Compares three message-list token estimators over synthetic 20/200/1000-
message histories, with and without image content:

    A. agent.model_metadata.estimate_messages_tokens_rough  (current default)
    B. agent.tokens.message_estimator.estimate_messages_tokens_fast (new,
       delegates text counting to agent.tokens.fast_estimator — tiktoken
       when installed, else the same len//4 naive formula)
    C. agent._hermes_fast.estimate_messages_tokens (Rust extension when
       built, else a pure-Python fallback)

Backend availability (tiktoken, the Rust extension) is reported honestly —
a backend that degrades to its naive fallback in this environment is
labeled as such, never presented as an accelerated-path measurement it
didn't actually exercise.

Usage:
    python3 scripts/bench_token_estimators.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Dict, List

from agent._hermes_fast import HAVE_RUST, estimate_messages_tokens as c_estimate
from agent.model_metadata import estimate_messages_tokens_rough as a_estimate
from agent.tokens.fast_estimator import has_tiktoken
from agent.tokens.message_estimator import estimate_messages_tokens_fast as b_estimate

SIZES = (20, 200, 1000)
REPEATS = 5

_SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. " * 3
    + "This message simulates a realistic chat turn with some tool output mixed in."
)

_SAMPLE_IMAGE_PART = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64," + ("A" * 400)},
}


def _build_messages(n: int, with_images: bool) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        if with_images and i % 10 == 0:
            content = [{"type": "text", "text": _SAMPLE_TEXT}, _SAMPLE_IMAGE_PART]
        else:
            content = _SAMPLE_TEXT
        messages.append({"role": role, "content": content})
    return messages


def _time_it(fn, messages: List[Dict[str, Any]]) -> Dict[str, float]:
    samples = []
    result = None
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        result = fn(messages)
        samples.append(time.perf_counter() - t0)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 4),
        "tokens": result,
    }


def run() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schema": "simplicio.token-estimator-bench/v1",
        "backends": {
            "A_rough_char_based": {"accelerated": False, "note": "always pure-Python char count"},
            "B_fast_estimator": {"accelerated": has_tiktoken(), "note": "tiktoken" if has_tiktoken() else "naive len//4 fallback (tiktoken not installed)"},
            "C_hermes_fast_rust": {"accelerated": HAVE_RUST, "note": "Rust extension" if HAVE_RUST else "pure-Python fallback (rust_ext not built)"},
        },
        "scenarios": [],
    }

    for n in SIZES:
        for with_images in (False, True):
            messages = _build_messages(n, with_images)
            scenario = {
                "message_count": n,
                "with_images": with_images,
                "A_rough": _time_it(a_estimate, messages),
                "B_fast_estimator": _time_it(b_estimate, messages),
                "C_hermes_fast": _time_it(c_estimate, messages),
            }
            report["scenarios"].append(scenario)

    return report


def print_report(report: Dict[str, Any]) -> None:
    print("Token estimator A/B/C bench (issue #111)")
    print()
    for name, meta in report["backends"].items():
        flag = "accelerated" if meta["accelerated"] else "fallback"
        print(f"  {name}: {flag} ({meta['note']})")
    print()
    header = f"{'msgs':>6} {'images':>7} {'A_rough_ms':>12} {'B_fast_ms':>11} {'C_rust_ms':>11}"
    print(header)
    print("-" * len(header))
    for s in report["scenarios"]:
        print(
            f"{s['message_count']:>6} {str(s['with_images']):>7} "
            f"{s['A_rough']['median_ms']:>12} {s['B_fast_estimator']['median_ms']:>11} "
            f"{s['C_hermes_fast']['median_ms']:>11}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=str, default=None, help="also write the report as JSON to this path")
    args = parser.parse_args(argv)

    report = run()
    print_report(report)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nWrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
