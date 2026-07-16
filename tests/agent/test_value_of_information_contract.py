from agent.value_of_information_contract import (
    ObservationOption,
    ValueOfInformationDecision,
    decide_observe_or_act,
)


def test_acts_when_fewer_than_two_hypotheses():
    decision = decide_observe_or_act(
        live_hypotheses=("h1",), action_cost=10.0, action_irreversible=True, observations=(),
    )
    assert decision.observe_or_act == "act"
    assert decision.chosen_observation == ""


def test_observes_cheapest_discriminating_option():
    decision = decide_observe_or_act(
        live_hypotheses=("h1", "h2"),
        action_cost=10.0,
        action_irreversible=True,
        observations=(
            ObservationOption("expensive_probe", 8.0, ("h1",)),
            ObservationOption("cheap_probe", 2.0, ("h2",)),
            ObservationOption("irrelevant_probe", 1.0, ("h3",)),
        ),
    )
    assert decision.observe_or_act == "observe"
    assert decision.chosen_observation == "cheap_probe"


def test_acts_when_no_observation_beats_action_cost():
    decision = decide_observe_or_act(
        live_hypotheses=("h1", "h2"),
        action_cost=1.0,
        action_irreversible=False,
        observations=(ObservationOption("costly_probe", 5.0, ("h1",)),),
    )
    assert decision.observe_or_act == "act"
    assert "no observation" in decision.reason


def test_rejects_negative_action_cost():
    try:
        decide_observe_or_act(
            live_hypotheses=("h1", "h2"), action_cost=-1.0, action_irreversible=False, observations=(),
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_observation_option_rejects_negative_cost():
    try:
        ObservationOption("x", -1.0, ())
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_decision_content_hash_is_deterministic():
    decision = decide_observe_or_act(
        live_hypotheses=("h1", "h2"),
        action_cost=10.0,
        action_irreversible=True,
        observations=(ObservationOption("cheap_probe", 2.0, ("h2",)),),
    )
    assert decision.content_hash() == decision.content_hash()
    assert decision.to_dict()["schema"] == "simplicio.value-of-information/v1"
