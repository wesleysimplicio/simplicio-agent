from agent.trajectory_skill_contract import TrajectorySkillCandidate

def test_only_verified_trajectories_are_eligible():
    candidate = TrajectorySkillCandidate("sha:run", "completed_verified", ("open", "verify"), "run:1", "fixture:1", .9)
    assert candidate.eligible
    assert len(candidate.content_hash()) == 64
