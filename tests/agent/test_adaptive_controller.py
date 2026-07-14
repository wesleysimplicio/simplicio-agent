import json

import pytest

from agent.adaptive_controller import (
    ADAPTIVE_CONTROLLER_SCHEMA,
    AdaptiveController,
    AdaptiveObservation,
    AdaptivePolicy,
    ControllerAction,
)


def _observation(**overrides):
    values = {"queue_pressure": 0.2, "cpu_pressure": 0.2, "memory_pressure": 0.2,
              "working_set_entropy": 0.2, "marginal_gain": 0.2, "current_concurrency": 2}
    values.update(overrides)
    return AdaptiveObservation(**values)


def test_pressure_throttles_and_hysteresis_prevents_flapping():
    controller = AdaptiveController()
    pressured = controller.decide(_observation(cpu_pressure=0.9, current_concurrency=4))
    assert pressured.action is ControllerAction.THROTTLE
    assert pressured.target_concurrency == 3
    held = controller.decide(_observation(cpu_pressure=0.7, current_concurrency=3), pressured.state)
    assert held.pressure_active
    assert held.action is ControllerAction.THROTTLE
    recovered = controller.decide(_observation(cpu_pressure=0.5, current_concurrency=2), held.state)
    assert not recovered.pressure_active


def test_scale_up_is_gain_and_entropy_gated_with_bounded_steps():
    controller = AdaptiveController(AdaptivePolicy(max_concurrency=5))
    first = controller.decide(_observation(queue_pressure=0.8, working_set_entropy=0.8,
                                           marginal_gain=0.5, current_concurrency=0))
    second = controller.decide(_observation(queue_pressure=0.8, working_set_entropy=0.8,
                                            marginal_gain=0.5, current_concurrency=first.target_concurrency),
                               first.state)
    assert (first.action, first.target_concurrency) == (ControllerAction.SCALE_UP, 1)
    assert (second.action, second.target_concurrency) == (ControllerAction.SCALE_UP, 2)
    assert second.target_concurrency <= 5


def test_low_gain_decays_without_falling_below_minimum():
    controller = AdaptiveController(AdaptivePolicy(min_concurrency=1, max_concurrency=8))
    decision = controller.decide(_observation(current_concurrency=3, marginal_gain=0.01))
    assert decision.action is ControllerAction.DECAY
    assert decision.target_concurrency == 2
    floor = controller.decide(_observation(current_concurrency=1, marginal_gain=0.01), decision.state)
    assert floor.target_concurrency == 1
    assert floor.action is ControllerAction.HOLD


def test_invalid_bounds_and_observations_fail_closed():
    with pytest.raises(ValueError):
        AdaptivePolicy(min_concurrency=3, max_concurrency=2)
    with pytest.raises(ValueError):
        AdaptiveObservation(2, 0, 0, 0, 0, 1)


def test_decision_wire_shape_is_deterministic_and_json_safe():
    decision = AdaptiveController().decide(_observation())
    payload = decision.to_dict()
    assert payload["schema"] == ADAPTIVE_CONTROLLER_SCHEMA
    assert json.loads(json.dumps(payload)) == payload
