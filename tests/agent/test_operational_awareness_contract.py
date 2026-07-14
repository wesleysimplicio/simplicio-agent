from agent.operational_awareness_contract import OperationalAwarenessContract


def test_awareness_contract_is_replayable_and_does_not_grant_authority():
    first = OperationalAwarenessContract(
        identity_ref="profile:one",
        goal_ref="goal:one",
        run_id="run:one",
        phase="observe",
        self_state={"health": "ready", "authority": "observe-only"},
        world_state={"page": "example", "freshness": "fresh"},
        attention=("stale belief", "human gate"),
        unknowns=("approval",),
    )
    replay = OperationalAwarenessContract(
        identity_ref="profile:one",
        goal_ref="goal:one",
        run_id="run:one",
        phase="observe",
        self_state={"authority": "observe-only", "health": "ready"},
        world_state={"freshness": "fresh", "page": "example"},
        attention=("human gate", "stale belief"),
        unknowns=("approval",),
    )
    assert first.to_dict()["schema"] == "simplicio.operational-awareness/v1"
    assert first.content_hash() == replay.content_hash()
    assert "allow" not in first.to_dict()["self_state"]
