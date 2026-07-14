"""Focused tests for the bounded fan-out governor contract."""

from __future__ import annotations

import math

from agent.fanout_governor_contract import (
    AdaptiveFanoutGovernor,
    FanoutGovernorConfig,
    FanoutMetrics,
    FanoutReasonCode,
    GovernorState,
    decide_fanout,
)


def test_serial_work_stays_at_one_worker() -> None:
    decision = decide_fanout(
        FanoutMetrics(
            queue_depth=100,
            arrival_rate_per_second=100,
            parallel_fraction=0.0,
        )
    )

    assert decision.valid_metrics
    assert decision.desired_workers == 1
    assert FanoutReasonCode.SERIAL_WORK in decision.reason_codes
    assert decision.amdahl is not None
    assert decision.amdahl.useful_workers == 1


def test_parallel_work_is_additive_and_never_exceeds_ceiling() -> None:
    config = FanoutGovernorConfig(max_workers=4, max_step_up=1)
    governor = AdaptiveFanoutGovernor(config)
    metrics = FanoutMetrics(queue_depth=100, arrival_rate_per_second=100, parallel_fraction=1.0)

    decisions = [governor.decide(metrics) for _ in range(8)]

    assert [decision.desired_workers for decision in decisions[:4]] == [2, 3, 4, 4]
    assert all(1 <= decision.desired_workers <= 4 for decision in decisions)
    assert all(
        abs(current.desired_workers - previous.desired_workers) <= 1
        for previous, current in zip(decisions, decisions[1:])
    )


def test_little_law_drives_bounded_worker_target() -> None:
    config = FanoutGovernorConfig(max_workers=8)
    decision = decide_fanout(
        FanoutMetrics(
            queue_depth=4,
            arrival_rate_per_second=2,
            service_time_seconds=1.0,
            parallel_fraction=1.0,
        ),
        config=config,
    )

    assert decision.little is not None
    assert decision.little.target_wip == 2.0
    assert decision.little.required_workers == 6
    assert decision.desired_workers == 2
    assert FanoutReasonCode.LITTLE_TARGET in decision.reason_codes


def test_pressure_and_failures_reduce_before_spawn() -> None:
    config = FanoutGovernorConfig(max_workers=8)
    decision = decide_fanout(
        FanoutMetrics(
            queue_depth=100,
            arrival_rate_per_second=100,
            parallel_fraction=1.0,
            cpu_pressure=0.95,
            failure_rate=0.50,
            current_workers=4,
        ),
        config=config,
        state=GovernorState(current_workers=4),
    )

    assert decision.desired_workers == 3
    assert FanoutReasonCode.PRESSURE_GUARD in decision.reason_codes
    assert FanoutReasonCode.FAILURE_GUARD in decision.reason_codes


def test_pid_has_hysteresis_filtering_and_anti_windup() -> None:
    config = FanoutGovernorConfig(max_workers=2, pid_kp=0.1, pid_ki=1.0, pid_kd=0.5)
    governor = AdaptiveFanoutGovernor(config)
    high_wait = FanoutMetrics(observed_wait_seconds=100, parallel_fraction=1.0)

    first = governor.decide(high_wait)
    second = governor.decide(high_wait)
    assert first.desired_workers == 2
    assert second.desired_workers == 2
    assert second.pid is not None and second.pid.anti_windup
    assert abs(second.next_state.integral_error) <= config.integral_limit

    recovery = governor.decide(FanoutMetrics(observed_wait_seconds=0.0, parallel_fraction=1.0))
    assert recovery.desired_workers == 1


def test_invalid_metrics_fail_closed_and_receipt_handles_nan() -> None:
    decision = decide_fanout(
        FanoutMetrics(
            parallel_fraction=math.nan,
            cpu_pressure=float("inf"),
            queue_depth=-1,
        )
    )

    assert not decision.valid_metrics
    assert decision.desired_workers == 1
    assert decision.reason_codes == (FanoutReasonCode.INVALID_METRICS.value,)
    assert '"parallel_fraction":null' in decision.receipt.canonical_json
    assert len(decision.receipt.digest) == 64


def test_non_numeric_metric_object_also_fails_closed() -> None:
    decision = decide_fanout(FanoutMetrics(queue_depth=object()))

    assert not decision.valid_metrics
    assert decision.desired_workers == 1
    assert '"queue_depth":null' in decision.receipt.canonical_json


def test_identical_inputs_produce_identical_receipts() -> None:
    metrics = FanoutMetrics(queue_depth=3, arrival_rate_per_second=1, parallel_fraction=0.8)

    first = decide_fanout(metrics)
    second = decide_fanout(metrics)

    assert first.to_dict() == second.to_dict()
    assert first.receipt.canonical_json == second.receipt.canonical_json
    assert first.receipt.sha256 == second.receipt.sha256


def test_invalid_policy_is_rejected_at_configuration_boundary() -> None:
    try:
        FanoutGovernorConfig(max_workers=0)
    except ValueError as exc:
        assert "max_workers" in str(exc)
    else:
        raise AssertionError("invalid policy must be rejected")
