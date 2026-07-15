from agent.backlog_ref import issue_315_self_mod_kernel as m


def test_commit_when_equiv_and_canary():
    k = m.SelfModKernel(state={"x": 1, "y": 9})
    def mut(s):
        s["x"] = 2
    def probe_eq(p, st):
        return st["y"] * 10  # invariant: probe output unchanged by mutating x
    r = k.apply(mut, "probe", probe_eq, canary=lambda s: s["x"] == 2)
    assert r.status == "committed"
    assert k.state["x"] == 2
    assert len(r.to_hbp()["snapshot_digest"]) == 32


def test_rollback_when_equiv_fails():
    k = m.SelfModKernel(state={"x": 1, "y": 5})
    def mut(s):
        s["y"] = 99  # changes probe output -> not equivalent
    def probe_eq(p, st):
        return st["y"]
    r = k.apply(mut, "p", probe_eq, canary=lambda s: True)
    assert r.status == "rolled_back"
    assert k.state["y"] == 5  # unchanged
    assert "rollback" in r.note


def test_rollback_when_canary_fails():
    k = m.SelfModKernel(state={"x": 1})
    def mut(s):
        s["x"] = 2
    def probe_eq(p, st):
        return 1
    r = k.apply(mut, "p", probe_eq, canary=lambda s: s["x"] == 1)  # canary rejects
    assert r.status == "rolled_back"
    assert k.state["x"] == 1
