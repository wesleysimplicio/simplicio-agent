import json
from pathlib import Path

import pytest

from agent.adaptive_controller import (
    ADAPTIVE_CONTROLLER_SCHEMA,
    AdaptiveController,
    AdaptiveObservation,
    AdaptivePolicy,
    ADAPTIVE_RECEIPT_SCHEMA,
    ControllerAction,
)


def _observation(**overrides):
    values = {
        "queue_pressure": 0.2,
        "cpu_pressure": 0.2,
        "memory_pressure": 0.2,
        "working_set_entropy": 0.2,
        "marginal_gain": 0.2,
        "current_concurrency": 2,
    }
    values.update(overrides)
    return AdaptiveObservation(**values)


def test_pressure_throttles_and_hysteresis_prevents_flapping():
    controller = AdaptiveController()
    pressured = controller.decide(_observation(cpu_pressure=0.9, current_concurrency=4))
    assert pressured.action is ControllerAction.THROTTLE
    assert pressured.target_concurrency == 3
    held = controller.decide(
        _observation(cpu_pressure=0.7, current_concurrency=3), pressured.state
    )
    assert held.pressure_active
    assert held.action is ControllerAction.THROTTLE
    recovered = controller.decide(
        _observation(cpu_pressure=0.5, current_concurrency=2), held.state
    )
    assert not recovered.pressure_active


def test_scale_up_is_gain_and_entropy_gated_with_bounded_steps():
    controller = AdaptiveController(AdaptivePolicy(max_concurrency=5))
    first = controller.decide(
        _observation(
            queue_pressure=0.8,
            working_set_entropy=0.8,
            marginal_gain=0.5,
            current_concurrency=0,
        )
    )
    second = controller.decide(
        _observation(
            queue_pressure=0.8,
            working_set_entropy=0.8,
            marginal_gain=0.5,
            current_concurrency=first.target_concurrency,
        ),
        first.state,
    )
    assert (first.action, first.target_concurrency) == (ControllerAction.SCALE_UP, 1)
    assert (second.action, second.target_concurrency) == (ControllerAction.SCALE_UP, 2)
    assert second.target_concurrency <= 5


def test_scale_up_is_minimal_one_step_even_when_queue_is_large():
    controller = AdaptiveController(AdaptivePolicy(max_concurrency=8))
    decision = controller.decide(
        _observation(
            queue_pressure=1.0,
            working_set_entropy=1.0,
            marginal_gain=1.0,
            current_concurrency=4,
        )
    )
    assert decision.action is ControllerAction.SCALE_UP
    assert decision.target_concurrency == 5


def test_bounded_fan_out_is_stable_and_receipt_safe():
    controller = AdaptiveController(AdaptivePolicy(max_concurrency=8, max_fan_out=3))
    decision = controller.decide(
        _observation(
            queue_pressure=0.8,
            working_set_entropy=0.8,
            marginal_gain=0.5,
            current_concurrency=1,
        )
    )
    plan = controller.bound_fan_out(["a", "b", "c", "d"], decision=decision)
    assert plan.items == ("a", "b")
    assert plan.receipt.allowed == 2
    assert plan.receipt.selected == 2
    assert plan.receipt.truncated
    assert plan.to_dict()["receipt"]["schema"] == ADAPTIVE_RECEIPT_SCHEMA


def test_pid_integral_is_bounded_and_receipt_is_json_stable():
    controller = AdaptiveController(
        AdaptivePolicy(
            integral_limit=0.25,
            proportional_gain=2.0,
            integral_gain=1.0,
            derivative_gain=1.0,
        )
    )
    first = controller.decide(_observation(cpu_pressure=1.0))
    second = controller.decide(_observation(cpu_pressure=1.0), first.state)
    assert first.pid_output == pytest.approx(1.45)
    assert second.state.integral_error == 0.25
    assert second.pid_output == pytest.approx(1.05)
    assert json.loads(json.dumps(second.to_dict())) == second.to_dict()


def test_fixture_routes_are_deterministic():
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "native"
        / "adaptive_controller_routes.json"
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    controller = AdaptiveController(AdaptivePolicy(max_concurrency=4, max_fan_out=4))
    for route in payload["routes"]:
        decision = controller.decide(AdaptiveObservation(**route["observation"]))
        assert decision.action.value == route["expected_action"], route["id"]
        assert decision.target_concurrency == route["expected_target"], route["id"]


def test_low_gain_decays_without_falling_below_minimum():
    controller = AdaptiveController(
        AdaptivePolicy(min_concurrency=1, max_concurrency=8)
    )
    decision = controller.decide(
        _observation(current_concurrency=3, marginal_gain=0.01)
    )
    assert decision.action is ControllerAction.DECAY
    assert decision.target_concurrency == 2
    floor = controller.decide(
        _observation(current_concurrency=1, marginal_gain=0.01), decision.state
    )
    assert floor.target_concurrency == 1
    assert floor.action is ControllerAction.HOLD


def test_invalid_bounds_and_observations_fail_closed():
    with pytest.raises(ValueError):
        AdaptivePolicy(min_concurrency=3, max_concurrency=2)
    with pytest.raises(ValueError):
        AdaptiveObservation(2, 0, 0, 0, 0, 1)
    with pytest.raises(ValueError):
        AdaptivePolicy(integral_limit="not-a-number")
    with pytest.raises(ValueError):
        AdaptiveObservation(0, 0, 0, 0, None, 1)


def test_decision_wire_shape_is_deterministic_and_json_safe():
    decision = AdaptiveController().decide(_observation())
    payload = decision.to_dict()
    assert payload["schema"] == ADAPTIVE_CONTROLLER_SCHEMA
    assert json.loads(json.dumps(payload)) == payload
