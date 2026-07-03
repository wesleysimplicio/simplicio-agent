#!/usr/bin/env python3
"""TOON-CONTRACT conformance runner for ``agent.toon_codec`` (issue #16, #149).

Walks ``tests/fixtures/toon-golden/`` per ``TOON-CONTRACT.md`` §6 (vendored
at the repo root from the canonical host, ``simplicio-mapper`` — issue
#149) and checks this repo's ``agent.toon_codec`` codec against every case.
Exits non-zero (and prints every failure) on any conformance gap.

Byte-identical match between a fresh ``to_toon(input.json)`` and the
committed ``expected.toon`` is NOT required here — per
``tests/fixtures/toon-golden/README.md``, that is only a requirement for
``simplicio-mapper``'s own codec (the reference implementation that
produced the fixtures). This runner checks the two cross-repo-safe
invariants instead:

  1. ``from_toon(to_toon(input.json)) == input.json``  (this repo's own
     round-trip is lossless)
  2. ``from_toon(expected.toon) == input.json``          (this repo's
     decoder can understand the canonical encoding another repo produced —
     the actual interop guarantee the contract exists for)

and, for every invalid case, that ``from_toon(input.toon)`` raises a
``ValueError``-family error (never a bare index/key error, TOON-CONTRACT.md
§5) whose message contains the case's ``reason_contains`` substring.

Usage: python3 scripts/toon_contract_runner.py
Also wired into the unit suite: tests/agent/test_toon_codec.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.toon_codec import from_toon, to_toon  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "fixtures", "toon-golden")


def _load_manifest() -> dict:
    with open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8") as handle:
        return json.load(handle)


def strict_equal(a: object, b: object) -> bool:
    """Round-trip equality that does NOT treat ``bool`` and ``int`` as
    interchangeable.

    Plain ``==`` in Python treats ``True == 1`` and ``False == 0``, so a
    codec bug that (incorrectly) collapses booleans to ``1``/``0`` could
    pass a naive ``decode(encode(x)) == x`` check even though it silently
    changed the value's type. Mirrors simplicio-mapper's own runner
    (wesleysimplicio/simplicio-mapper#151).
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def check_valid_case(case_id: str) -> list[str]:
    """Return a list of failure messages (empty = pass) for a valid case."""
    failures: list[str] = []
    case_dir = os.path.join(CORPUS, "valid", case_id)
    with open(os.path.join(case_dir, "input.json"), encoding="utf-8") as handle:
        expected_value = json.load(handle)
    with open(os.path.join(case_dir, "expected.toon"), encoding="utf-8") as handle:
        expected_toon = handle.read().rstrip("\n")

    fresh_encoded = to_toon(expected_value)
    if not strict_equal(from_toon(fresh_encoded), expected_value):
        failures.append(f"{case_id}: from_toon(to_toon(input.json)) != input.json (round-trip)")
    if not strict_equal(from_toon(expected_toon), expected_value):
        failures.append(f"{case_id}: from_toon(expected.toon) != input.json (cross-repo interop)")
    return failures


def check_invalid_case(case_id: str) -> list[str]:
    """Return a list of failure messages (empty = pass) for an invalid case."""
    failures: list[str] = []
    case_dir = os.path.join(CORPUS, "invalid", case_id)
    with open(os.path.join(case_dir, "input.toon"), encoding="utf-8") as handle:
        text = handle.read()
    with open(os.path.join(case_dir, "meta.json"), encoding="utf-8") as handle:
        meta = json.load(handle)

    try:
        result = from_toon(text)
    except ValueError as error:
        message = str(error)
        reason = meta.get("reason_contains")
        if reason and reason not in message:
            failures.append(
                f"{case_id}: from_toon raised {type(error).__name__} but message "
                f"{message!r} does not contain expected substring {reason!r}"
            )
    except Exception as error:  # noqa: BLE001 - this IS the check (TOON-CONTRACT.md §5)
        failures.append(
            f"{case_id}: from_toon raised {type(error).__name__} ({error}) instead of a "
            "ValueError-family error (TOON-CONTRACT.md §5: never a bare index/key error)"
        )
    else:
        failures.append(f"{case_id}: from_toon did not raise; expected a decode error, got {result!r}")
    return failures


def run() -> int:
    manifest = _load_manifest()
    failures: list[str] = []
    for case in manifest.get("valid", []):
        failures.extend(check_valid_case(case["id"]))
    for case in manifest.get("invalid", []):
        failures.extend(check_invalid_case(case["id"]))

    total = len(manifest.get("valid", [])) + len(manifest.get("invalid", []))
    if failures:
        print(f"TOON-CONTRACT conformance: {len(failures)} failure(s) of {total} case(s)")
        for message in failures:
            print(f"  - {message}")
        return 1
    print(f"TOON-CONTRACT conformance: {total}/{total} case(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
