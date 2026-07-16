from agent.coarse_graining_contract import (
    CoarseGrainLevel,
    MicroEvent,
    build_trace,
)


def _events():
    return (
        MicroEvent("h1", "tool_call: read_file(a.py)"),
        MicroEvent("h2", "tool_call: edit_file(a.py)"),
        MicroEvent("h3", "test_run: pytest passed"),
    )


def test_build_trace_links_every_level_back_to_micro_handles():
    micro = _events()
    levels = (
        CoarseGrainLevel("meso", "edited a.py and reran tests", ("h1", "h2", "h3")),
        CoarseGrainLevel("macro", "fixed bug in a.py", ("h1", "h2", "h3")),
        CoarseGrainLevel("narrative", "resolved the reported issue", ("h1", "h2", "h3")),
    )
    trace = build_trace(micro, levels)
    assert trace.expand(2) == micro  # narrative level expands back to all 3 micro events


def test_non_micro_level_requires_source_handles():
    try:
        CoarseGrainLevel("meso", "summary", ())
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_trace_rejects_unknown_handle():
    micro = _events()
    levels = (CoarseGrainLevel("meso", "summary", ("h1", "does-not-exist")),)
    try:
        build_trace(micro, levels)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "does-not-exist" in str(exc)


def test_micro_event_rejects_empty_content():
    try:
        MicroEvent("h1", "   ")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_level_rejects_invalid_level_name():
    try:
        CoarseGrainLevel("nano", "summary", ("h1",))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_trace_content_hash_is_deterministic():
    micro = _events()
    levels = (CoarseGrainLevel("meso", "summary", ("h1",)),)
    trace = build_trace(micro, levels)
    assert trace.content_hash() == trace.content_hash()
    assert trace.to_dict()["schema"] == "simplicio.coarse-graining/v1"
