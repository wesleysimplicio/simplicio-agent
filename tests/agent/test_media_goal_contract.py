from agent.media_goal_contract import MediaGoalContract

def test_media_goal_declares_inputs_timeline_and_verifier():
    goal = MediaGoalContract("trim video", ("asset:1",), "mp4", 12.5, 30, "ffprobe", "timeline:1")
    assert goal.to_dict()["schema"] == "simplicio.media-goal/v1"
    assert len(goal.content_hash()) == 64
