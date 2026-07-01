import pytest

from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    session_db = SessionDB(db_path=tmp_path / "state.db")
    yield session_db
    session_db.close()


def test_handoff_state_tracks_updated_at_across_transitions(db, monkeypatch):
    db.create_session("sess-1", source="cli")

    times = iter([100.0, 150.0, 220.0, 260.0, 330.0])
    monkeypatch.setattr("hermes_state.time.time", lambda: next(times))

    assert db.request_handoff("sess-1", "telegram") is True
    pending = db.get_handoff_state("sess-1")
    assert pending == {
        "state": "pending",
        "platform": "telegram",
        "error": None,
        "updated_at": 100.0,
    }

    assert db.claim_handoff("sess-1") is True
    running = db.get_handoff_state("sess-1")
    assert running == {
        "state": "running",
        "platform": "telegram",
        "error": None,
        "updated_at": 150.0,
    }

    db.complete_handoff("sess-1")
    completed = db.get_handoff_state("sess-1")
    assert completed == {
        "state": "completed",
        "platform": "telegram",
        "error": None,
        "updated_at": 220.0,
    }

    assert db.request_handoff("sess-1", "discord") is True
    db.fail_handoff("sess-1", "gateway offline")
    failed = db.get_handoff_state("sess-1")
    assert failed == {
        "state": "failed",
        "platform": "discord",
        "error": "gateway offline",
        "updated_at": 330.0,
    }
