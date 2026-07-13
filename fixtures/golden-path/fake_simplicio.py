from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_scenario() -> dict:
    scenario_path = os.environ.get("GOLDEN_PATH_SCENARIO")
    if not scenario_path:
        raise SystemExit("missing GOLDEN_PATH_SCENARIO")
    return json.loads(Path(scenario_path).read_text(encoding="utf-8"))


def _mutation_path(scenario: dict) -> Path:
    scenario_path = Path(os.environ["GOLDEN_PATH_SCENARIO"]).resolve()
    return (scenario_path.parent / scenario["mutation"]["path"]).resolve()


def _absolute_write_set(scenario: dict) -> list[str]:
    scenario_path = Path(os.environ["GOLDEN_PATH_SCENARIO"]).resolve()
    return [
        str((scenario_path.parent / relative_path).resolve())
        for relative_path in scenario["write_set"]
    ]


def _apply_mutation(scenario: dict) -> dict:
    mutation = scenario["mutation"]
    target = _mutation_path(scenario)
    current = target.read_text(encoding="utf-8")
    if current != mutation["expected_before"]:
        raise SystemExit("unexpected pre-edit content")
    target.write_text(mutation["expected_after"], encoding="utf-8")
    return {
        "applied": True,
        "files_modified": [str(target)],
        "write_set": _absolute_write_set(scenario)
    }


def _validate_workspace(scenario: dict, command: str) -> dict:
    mutation = scenario["mutation"]
    target = _mutation_path(scenario)
    observed = target.read_text(encoding="utf-8")
    matches = observed == mutation["expected_after"]
    return {
        "command": command,
        "decision": "allow" if matches else "deny",
        "target": str(target),
        "matches_expected": matches,
        "observed": observed,
        "expected": mutation["expected_after"]
    }


def main(argv: list[str]) -> int:
    scenario = _load_scenario()
    if argv[:2] == ["runtime", "map"]:
        payload = {
            "repo": str(Path(os.environ["GOLDEN_PATH_SCENARIO"]).resolve().parent / "workspace"),
            "format": "json",
            "write_set": _absolute_write_set(scenario)
        }
    elif argv[:2] == ["checkpoint", "record"]:
        extra = json.loads(sys.stdin.read() or "{}")
        payload = {
            "label": extra.get("label", "golden-path-lease"),
            "lease": extra.get("lease", scenario["lease"]),
            "workdir": extra.get("workdir", ""),
            "write_set": _absolute_write_set(scenario)
        }
    elif argv[:1] == ["edit"]:
        payload = _apply_mutation(scenario)
    elif argv[:2] == ["gate", "classify"]:
        action = ""
        if "--action" in argv:
            action = argv[argv.index("--action") + 1]
        payload = _validate_workspace(scenario, action)
    elif argv[:2] == ["ledger", "append"]:
        event = json.loads(sys.stdin.read() or "{}")
        payload = {"accepted": True, "event": event}
    else:
        print(json.dumps({"error": f"unsupported command: {argv}"}), file=sys.stderr)
        return 2

    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
