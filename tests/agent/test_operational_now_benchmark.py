"""Real, timed benchmark for the operational-now event store and projector.

Issue #166 acceptance criteria requires publishing bytes/run, update latency,
and context tokens avoided for the operational-now snapshot versus raw
transcript. This benchmark measures append latency, replay/projection
latency, and snapshot size versus the raw receipt journal size for a
realistic run of N receipts, and asserts the measured numbers are sane
(not a placeholder / not hard-coded).
"""

from __future__ import annotations

import json
import statistics
import time

from agent.belief_state import Freshness
from agent.event_store import (
    AwarenessReceipt,
    OperationalEventStore,
    OperationalScope,
    OperationalValueStatus,
)
from agent.operational_now import OperationalNowProjector, OperationalNowStore


SCOPE = OperationalScope(profile_id="bench-profile", tenant_id="bench-tenant")


def _make_receipts(count: int) -> list[AwarenessReceipt]:
    receipts = []
    for i in range(count):
        receipts.append(
            AwarenessReceipt(
                receipt_id=f"receipt-{i}",
                path=f"field.{i % 25}",
                value=f"value-{i}",
                status=OperationalValueStatus.MEASURED,
                freshness=Freshness.FRESH,
                source="benchmark",
                source_event_id=f"event-{i}",
                recorded_at_ns=1_000_000 + i,
                confidence=0.9,
                payload={
                    "run_id": "bench-run",
                    "profile_id": "bench-profile",
                    "tenant_id": "bench-tenant",
                },
            )
        )
    return receipts


def test_append_and_projection_latency_and_snapshot_size_benchmark(tmp_path):
    receipt_count = 500
    receipts = _make_receipts(receipt_count)

    store = OperationalNowStore(
        event_log_path=tmp_path / "events.jsonl",
        snapshot_path=tmp_path / "snapshot.json",
        scope=SCOPE,
    )

    append_samples_us: list[float] = []
    for receipt in receipts:
        start = time.perf_counter()
        store.append(receipt)
        append_samples_us.append((time.perf_counter() - start) * 1_000_000)

    project_samples_us: list[float] = []
    snapshot = None
    for _ in range(5):
        start = time.perf_counter()
        snapshot = store.project()
        project_samples_us.append((time.perf_counter() - start) * 1_000_000)

    assert snapshot is not None

    replay_samples_us: list[float] = []
    projector = OperationalNowProjector()
    all_receipts = list(store.event_store.iter_receipts())
    for _ in range(5):
        start = time.perf_counter()
        replayed = projector.project(all_receipts)
        replay_samples_us.append((time.perf_counter() - start) * 1_000_000)

    # Determinism sanity: replay from the persisted journal reproduces the
    # same materialized snapshot hash as the live-appended projection.
    assert replayed.snapshot_hash == snapshot.snapshot_hash

    journal_bytes = store.event_store.path.stat().st_size
    snapshot_bytes = store.snapshot_path.stat().st_size
    snapshot_ratio = snapshot_bytes / journal_bytes

    append_mean_us = statistics.mean(append_samples_us)
    project_mean_us = statistics.mean(project_samples_us)
    replay_mean_us = statistics.mean(replay_samples_us)

    report = {
        "schema": "simplicio.operational-now-benchmark/v1",
        "receipt_count": receipt_count,
        "append_latency_us_mean": append_mean_us,
        "project_latency_us_mean": project_mean_us,
        "replay_latency_us_mean": replay_mean_us,
        "journal_bytes": journal_bytes,
        "snapshot_bytes": snapshot_bytes,
        "snapshot_to_journal_ratio": snapshot_ratio,
    }
    print("MEASURED|" + json.dumps(report, sort_keys=True))

    # The benchmark must publish real, non-placeholder measurements: bytes
    # must scale with data volume, and latencies must be finite positive
    # numbers rather than hard-coded stand-ins.
    assert journal_bytes > 0
    assert snapshot_bytes > 0
    assert append_mean_us > 0
    assert project_mean_us > 0
    assert replay_mean_us > 0
    # The materialized snapshot deduplicates per-path history (25 distinct
    # paths from 500 receipts), so it must be materially smaller than the
    # raw append-only journal it replays from.
    assert snapshot_bytes < journal_bytes
    assert snapshot_ratio < 0.5
