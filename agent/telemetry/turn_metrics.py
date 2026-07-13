"""Per-turn performance ledger (issue #119).

Wires the existing, previously-dormant ``agent.perf_probe.TurnLatencyProbe``
(instantiated once per turn in ``conversation_loop.run_conversation`` since
issue #244, but never finalized or persisted anywhere) into a durable JSONL
ledger with real, wall-clock-measured numbers: time-to-first-token (TTFT),
tool-loop duration, total turn duration, and tool-call count.

Every record's ``proof_kind`` is unconditionally ``"measured"`` — these are
real ``time.monotonic()`` deltas captured at the actual streaming/tool-call
boundaries (see ``agent/perf_probe.py`` and the ``mark_first_token``/
``mark_tool_calls``/``begin("tool")`` call sites in
``agent/conversation_loop.py``), never an estimate or heuristic.

Best-effort: any failure while writing a record is swallowed (telemetry must
never break a real turn), mirroring ``agent/telemetry/stage_timer.py``.
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agent.perf_probe import TurnLatencySample

SCHEMA = "simplicio.turn-metrics/v1"

_ENV_LEDGER_PATH = "HERMES_TURN_METRICS_LOG"
_DEFAULT_LEDGER_PATH = Path.home() / ".hermes" / "telemetry" / "turn_metrics.jsonl"

_log_path: Optional[Path] = None


def set_log_path(path: str | os.PathLike[str]) -> None:
    """Override the JSONL output path (mainly for tests)."""
    global _log_path
    _log_path = Path(path)


def get_log_path() -> Path:
    if _log_path is not None:
        return _log_path
    env = os.environ.get(_ENV_LEDGER_PATH)
    return Path(env) if env else _DEFAULT_LEDGER_PATH


def record_turn_metrics(sample: TurnLatencySample) -> None:
    """Append one turn's latency sample to the JSONL ledger. Best-effort."""
    try:
        record = {
            "schema": SCHEMA,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "proof_kind": "measured",
            **sample.as_dict(),
        }
        path = get_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - telemetry must never break a turn
        return


def _iter_records(path: Optional[Path] = None) -> Iterable[Dict[str, Any]]:
    p = path or get_log_path()
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def summarize_turn_metrics(path: Optional[Path] = None) -> Dict[str, Any]:
    """Aggregate p50/p95 for ttft_s and total_s across all recorded turns.

    Returns a dict with ``count`` and, when at least one sample has a
    numeric value for a given metric, ``p50``/``p95`` for it. A metric with
    zero eligible samples (e.g. no turn ever streamed, so no TTFT was ever
    captured) is simply absent from the result rather than reported as 0 —
    a 0 would misleadingly imply a real zero-latency measurement.
    """
    ttft_samples: List[float] = []
    total_samples: List[float] = []
    tool_samples: List[float] = []
    count = 0
    for rec in _iter_records(path):
        count += 1
        ttft = rec.get("ttft_s")
        if isinstance(ttft, (int, float)):
            ttft_samples.append(float(ttft))
        total = rec.get("total_s")
        if isinstance(total, (int, float)):
            total_samples.append(float(total))
        tool_s = rec.get("tool_s")
        if isinstance(tool_s, (int, float)):
            tool_samples.append(float(tool_s))

    out: Dict[str, Any] = {"count": count}
    for label, samples in (("ttft", ttft_samples), ("total", total_samples), ("tool", tool_samples)):
        if samples:
            out[f"{label}_p50_s"] = round(_percentile(samples, 0.50), 3)
            out[f"{label}_p95_s"] = round(_percentile(samples, 0.95), 3)
    return out


def finalize_and_record_turn(agent: Any) -> None:
    """Finish the agent's ``_latency_probe`` (if any) and record it.

    Called from a wrapper around ``run_conversation`` so it fires on every
    exit path (normal return, early return, or exception) — see
    ``conversation_loop.run_conversation``'s ``@_record_turn_metrics``
    decorator. Best-effort: never raises.
    """
    try:
        probe = getattr(agent, "_latency_probe", None)
        if probe is None:
            return
        sample = probe.finish()
        record_turn_metrics(sample)
    except Exception:  # noqa: BLE001 - telemetry must never break a turn
        return
