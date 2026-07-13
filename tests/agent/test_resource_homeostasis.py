import json
from pathlib import Path

from agent.resource_homeostasis import (
    ActionKind,
    Comparison,
    HomeostasisMode,
    HomeostasisPolicy,
    HomeostasisSnapshot,
    HomeostasisState,
    HysteresisThreshold,
    QualityObservation,
    ReceiptStatus,
    ResourceHomeostasisController,
    ResourceObservation,
    SafetyObservation,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "homeostasis"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _policy(*, budget: float = 10.0) -> HomeostasisPolicy:
    return HomeostasisPolicy(
        resource_thresholds={
            "cpu": HysteresisThreshold(enter=0.8, exit=0.6, comparison=Comparison.ABOVE),
            "memory": HysteresisThreshold(enter=0.9, exit=0.7, comparison=Comparison.ABOVE),
        },
        quality_thresholds={
            "response_quality": HysteresisThreshold(
                enter=0.5, exit=0.7, comparison=Comparison.BELOW
            )
        },
        resource_actions={
            "cpu": ActionKind.REDUCE_CONCURRENCY,
            "memory": ActionKind.SHED_LOAD,
        },
        action_costs={
            ActionKind.REDUCE_CONCURRENCY: 2.0,
            ActionKind.SHED_LOAD: 2.0,
            ActionKind.REDUCE_OPTIONAL_WORK: 1.0,
            ActionKind.PAUSE_AUTONOMY: 1.0,
            ActionKind.ENTER_FAIL_SAFE: 1.0,
            ActionKind.RESTORE_CAPACITY: 1.0,
            ActionKind.NOOP: 0.0,
        },
        max_total_cost=budget,
        required_safety=("secret_exposure",),
    )


def test_hysteresis_keeps_pressure_active_until_exit_threshold():
    controller = ResourceHomeostasisController(_policy())

    first = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.85, "ratio"), ResourceObservation("memory", 0.40, "ratio")),
            quality=(QualityObservation("response_quality", 0.95, "ratio"),),
            safety=(SafetyObservation("secret_exposure", True),),
        )
    )

    assert first.mode is HomeostasisMode.DEGRADED
    assert [action.kind for action in first.actions] == [ActionKind.REDUCE_CONCURRENCY]
    assert first.state.active_resource_pressure == ("cpu",)

    second = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.70, "ratio"), ResourceObservation("memory", 0.40, "ratio")),
            quality=(QualityObservation("response_quality", 0.95, "ratio"),),
            safety=(SafetyObservation("secret_exposure", True),),
        ),
        state=first.state,
    )

    assert second.mode is HomeostasisMode.DEGRADED
    assert second.state.active_resource_pressure == ("cpu",)

    third = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.55, "ratio"), ResourceObservation("memory", 0.40, "ratio")),
            quality=(QualityObservation("response_quality", 0.95, "ratio"),),
            safety=(SafetyObservation("secret_exposure", True),),
        ),
        state=second.state,
    )

    assert third.mode is HomeostasisMode.NOMINAL
    assert third.actions[-1].kind is ActionKind.RESTORE_CAPACITY
    assert third.state.active_resource_pressure == ()


def test_quality_pressure_and_budget_produce_deterministic_receipts():
    controller = ResourceHomeostasisController(_policy(budget=2.0))

    decision = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.91, "ratio"), ResourceObservation("memory", 0.95, "ratio")),
            quality=(QualityObservation("response_quality", 0.40, "ratio"),),
            safety=(SafetyObservation("secret_exposure", True),),
        )
    )

    assert decision.mode is HomeostasisMode.DEGRADED
    assert [action.target for action in decision.actions] == ["cpu"]
    assert [receipt.target for receipt in decision.receipts] == [
        "cpu",
        "memory",
        "response_quality",
    ]
    assert decision.receipts[0].status is ReceiptStatus.APPLIED
    assert decision.receipts[1].status is ReceiptStatus.SKIPPED_BUDGET
    assert decision.receipts[2].status is ReceiptStatus.SKIPPED_BUDGET


def test_unsafe_or_missing_observations_force_fail_safe_degradation():
    controller = ResourceHomeostasisController(_policy())

    unsafe = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.20, "ratio"), ResourceObservation("memory", 0.20, "ratio")),
            quality=(QualityObservation("response_quality", 0.90, "ratio"),),
            safety=(SafetyObservation("secret_exposure", False, detail="log leak"),),
        )
    )

    assert unsafe.mode is HomeostasisMode.FAIL_SAFE
    assert [action.kind for action in unsafe.actions[:2]] == [
        ActionKind.ENTER_FAIL_SAFE,
        ActionKind.PAUSE_AUTONOMY,
    ]
    assert "unsafe:secret_exposure" in unsafe.reasons

    missing = controller.evaluate(
        HomeostasisSnapshot(
            resources=(ResourceObservation("cpu", 0.20, "ratio"),),
            quality=(QualityObservation("response_quality", 0.90, "ratio"),),
            safety=(),
        )
    )

    assert missing.mode is HomeostasisMode.FAIL_SAFE
    assert "missing_resource:memory" in missing.reasons
    assert "missing_safety:secret_exposure" in missing.reasons


def test_evidence_is_redacted_and_fixture_round_trip_is_json_safe():
    fixture = _fixture("scenario.json")
    controller = ResourceHomeostasisController(_policy(budget=fixture["budget"]))

    decision = controller.evaluate(
        HomeostasisSnapshot(
            resources=tuple(
                ResourceObservation(
                    item["name"],
                    item["value"],
                    item["unit"],
                    evidence=item["evidence"],
                )
                for item in fixture["resources"]
            ),
            quality=tuple(
                QualityObservation(
                    item["name"],
                    item["value"],
                    item["unit"],
                    evidence=item["evidence"],
                )
                for item in fixture["quality"]
            ),
            safety=tuple(
                SafetyObservation(
                    item["name"],
                    item["safe"],
                    detail=item.get("detail", ""),
                    evidence=item["evidence"],
                )
                for item in fixture["safety"]
            ),
        ),
        state=HomeostasisState(mode=fixture["prior_mode"]),
    )

    assert decision.mode is HomeostasisMode.DEGRADED
    assert decision.evidence["resources"]["cpu"]["evidence"]["api_key"] == "[REDACTED]"
    assert decision.evidence["resources"]["cpu"]["evidence"]["nested"]["token"] == "[REDACTED]"
    assert decision.evidence["safety"]["secret_exposure"]["evidence"]["Authorization"] == "[REDACTED]"

    payload = decision.to_dict()
    assert payload["mode"] == "degraded"
    assert json.loads(json.dumps(payload))["receipts"][0]["action"] == "reduce_concurrency"
