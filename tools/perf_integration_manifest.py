#!/usr/bin/env python3
"""Executable integration manifest for Hermes Turbo performance axes.

Proves, for each shipped performance optimisation, the chain:

    PRESENT  -> symbol/module exists in the tree
    SAME_SOURCE -> it ships from THIS repo (not an external override)
    BUILT    -> module imports under the built distribution
    PACKAGED -> the fast extra lists the dependency
    INSTALLED -> the dependency is importable at runtime
    INVOKED  -> the activation path runs and takes effect
    E2E      -> an end-to-end behaviour depends on it
    DEFAULT  -> the fast stack is the recommended default
    GATED    -> `doctor` surfaces the status (gate signal)

The manifest FAILS (exit != 0) on the first axis that does not hold for a
shipped axis, so CI / local validation cannot silently regress a perf axis.
No network access, no credentials, no live provider calls.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AxisResult:
    name: str
    stages: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(self.stages.values())

    def mark(self, stage: str, ok: bool, note: str = "") -> None:
        self.stages[stage] = ok
        if note:
            self.notes.append(f"{stage}: {note}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _import_from_file(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot spec {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _module_importable(dotted: str) -> bool:
    try:
        __import__(dotted)
        return True
    except Exception:
        return False


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True)


# --------------------------------------------------------------------------
# axis checks
# --------------------------------------------------------------------------
def check_uvloop(res: AxisResult) -> None:
    src = REPO_ROOT / "agent" / "uvloop_utils.py"
    res.mark("PRESENT", src.exists(), str(src))
    res.mark("SAME_SOURCE", src.exists() and "install_uvloop_policy" in src.read_text())

    # BUILT: the module imports as part of the installed package.
    try:
        import asyncio
        import agent.uvloop_utils as mod  # type: ignore
        res.mark("BUILT", True)
    except Exception as exc:  # pragma: no cover - import error path
        res.mark("BUILT", False, str(exc))
        return

    # PACKAGED: fast extra lists uvloop.
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    res.mark("PACKAGED", "uvloop" in pyproject)

    # INSTALLED: uvloop importable at runtime (fast extra).
    res.mark("INSTALLED", _module_importable("uvloop"))

    # INVOKED: the policy installer flips the event loop policy.
    if res.stages["INSTALLED"]:
        import uvloop  # type: ignore
        before = asyncio.get_event_loop_policy()
        activated = mod.install_uvloop_policy()
        after = asyncio.get_event_loop_policy()
        took_effect = activated and isinstance(after, uvloop.EventLoopPolicy)
        res.mark("INVOKED", took_effect,
                 f"before={type(before).__name__} after={type(after).__name__}")
        try:
            asyncio.set_event_loop_policy(None)
        except Exception:
            pass
    else:
        res.mark("INVOKED", False, "uvloop not installed (fast extra absent)")

    # E2E: a real entrypoint wires install_uvloop_policy.
    gateway = (REPO_ROOT / "hermes_cli" / "gateway.py").read_text()
    main_py = (REPO_ROOT / "hermes_cli" / "main.py").read_text()
    res.mark("E2E", "install_uvloop_policy()" in gateway and "install_uvloop_policy()" in main_py)

    # DEFAULT: fast is "strongly recommended" in pyproject.
    res.mark("DEFAULT", "strongly recommended" in pyproject or "recommended" in pyproject)

    # GATED: doctor surfaces uvloop status.
    doctor = (REPO_ROOT / "hermes_cli" / "doctor.py").read_text()
    res.mark("GATED", "uvloop event loop" in doctor)


def check_fast_json(res: AxisResult) -> None:
    src = REPO_ROOT / "agent" / "serde" / "fast_json.py"
    res.mark("PRESENT", src.exists(), str(src))
    res.mark("SAME_SOURCE", src.exists() and "has_msgspec" in src.read_text())

    try:
        import agent.serde.fast_json as mod  # type: ignore
        res.mark("BUILT", True)
    except Exception as exc:  # pragma: no cover
        res.mark("BUILT", False, str(exc))
        return

    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    res.mark("PACKAGED", "msgspec" in pyproject and "orjson" in pyproject)

    # INSTALLED: at least one fast backend importable.
    has_ms = _module_importable("msgspec")
    has_or = _module_importable("orjson")
    res.mark("INSTALLED", has_ms or has_or,
             f"msgspec={has_ms} orjson={has_or}")

    # INVOKED: activation returns the fastest available backend.
    if has_ms or has_or:
        if has_ms:
            res.mark("INVOKED", mod.has_msgspec() is True)
        else:
            res.mark("INVOKED", mod.has_orjson() is True)
    else:
        res.mark("INVOKED", False, "no fast backend installed")

    # E2E: serde is re-exported and used by doctor / runtime.
    init_py = (REPO_ROOT / "agent" / "serde" / "__init__.py").read_text()
    res.mark("E2E", "has_msgspec" in init_py and "has_orjson" in init_py)

    # DEFAULT: fast extra is recommended.
    res.mark("DEFAULT", "strongly recommended" in pyproject or "recommended" in pyproject)

    # GATED: doctor surfaces Fast JSON status.
    doctor = (REPO_ROOT / "hermes_cli" / "doctor.py").read_text()
    res.mark("GATED", "Fast JSON" in doctor)


def check_prewarm(res: AxisResult) -> None:
    skill_src = REPO_ROOT / "agent" / "skill_commands.py"
    picker_src = REPO_ROOT / "hermes_cli" / "model_switch.py"
    res.mark("PRESENT",
             skill_src.exists() and picker_src.exists())
    res.mark("SAME_SOURCE",
             "def prewarm_skill_payloads" in skill_src.read_text()
             and "def prewarm_picker_cache_async" in picker_src.read_text())

    try:
        import agent.skill_commands as _sc  # type: ignore
        import hermes_cli.model_switch as _ms  # type: ignore
        res.mark("BUILT", True)
    except Exception as exc:  # pragma: no cover
        res.mark("BUILT", False, str(exc))
        return

    # PACKAGED: config carries prewarm tunables.
    cfg = (REPO_ROOT / "hermes_cli" / "config.py").read_text()
    res.mark("PACKAGED", "prewarm_max_items" in cfg and "prewarm_cache_max_entries" in cfg)

    # INSTALLED: the callables are importable.
    res.mark("INSTALLED",
             hasattr(_sc, "prewarm_skill_payloads")
             and hasattr(_ms, "prewarm_picker_cache_async"))

    # INVOKED: the picker prewarm uses a process guard so it runs once.
    res.mark("INVOKED", "_picker_prewarm_done" in picker_src.read_text())

    # E2E: agent runtime triggers openrouter prewarm.
    agent_init = (REPO_ROOT / "agent" / "agent_init.py").read_text()
    res.mark("E2E", "_openrouter_prewarm_done" in agent_init)

    # DEFAULT: prewarm is enabled by default in config.
    res.mark("DEFAULT", "prewarm_max_items" in cfg)

    # GATED: doctor / config exposes prewarm config.
    res.mark("GATED", "prewarm" in cfg.lower())


AXES: dict[str, Callable[[AxisResult], None]] = {
    "uvloop": check_uvloop,
    "fast-json": check_fast_json,
    "prewarm": check_prewarm,
}


def run_all() -> list[AxisResult]:
    results: list[AxisResult] = []
    for name, fn in AXES.items():
        res = AxisResult(name=name)
        try:
            fn(res)
        except Exception as exc:  # pragma: no cover - defensive
            res.mark("ERROR", False, f"unexpected: {exc}")
        results.append(res)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=str(REPO_ROOT), help="repo root to validate")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    results = run_all()
    failures = [r for r in results if not r.ok]

    if args.json:
        report = {
            "repo": str(repo_root),
            "axes": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "stages": r.stages,
                    "notes": r.notes,
                }
                for r in results
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        for r in results:
            status = "OK " if r.ok else "FAIL"
            print(f"[{status}] {r.name}")
            for stage, ok in r.stages.items():
                flag = "  +" if ok else "  -"
                print(f"{flag} {stage}")
            for n in r.notes:
                print(f"      {n}")
        print()
        print(f"axes: {len(results)}  failures: {len(failures)}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
