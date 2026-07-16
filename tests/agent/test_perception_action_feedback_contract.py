from agent.perception_action_feedback_contract import (
    PlannedAction,
    gate_action,
    hash_state,
)


def test_fires_when_state_unchanged():
    state = hash_state("<dom>button#submit</dom>")
    planned = PlannedAction("click", "button#submit", state)
    verdict = gate_action(planned, state)
    assert verdict.should_fire is True
    assert verdict.verdict == "fire"


def test_forces_reobserve_when_state_changed():
    planned_state = hash_state("<dom>button#submit</dom>")
    current_state = hash_state("<dom>modal#overlay open</dom>")
    planned = PlannedAction("click", "button#submit", planned_state)
    verdict = gate_action(planned, current_state)
    assert verdict.should_fire is False
    assert verdict.verdict == "reobserve"
    assert "stale" in verdict.reason


def test_planned_action_rejects_empty_fields():
    try:
        PlannedAction("", "target", "hash")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_gate_action_rejects_empty_current_state():
    planned = PlannedAction("click", "button", "hash")
    try:
        gate_action(planned, "")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_hash_state_is_deterministic_and_content_sensitive():
    assert hash_state("same") == hash_state("same")
    assert hash_state("a") != hash_state("b")


def test_verdict_content_hash_and_schema():
    state = hash_state("x")
    verdict = gate_action(PlannedAction("click", "x", state), state)
    assert verdict.content_hash() == verdict.content_hash()
    assert verdict.to_dict()["schema"] == "simplicio.perception-action-feedback/v1"
