import pytest

from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    session_db = SessionDB(db_path=tmp_path / "state.db")
    yield session_db
    session_db.close()


def test_export_handoff_markdown_renders_recent_cross_session_transcript(db):
    db.create_session("root", source="cli")
    db.set_session_title("root", "Root title")
    db.append_message("root", role="user", content="root question", timestamp=100)
    db.append_message("root", role="assistant", content="root answer", timestamp=110)

    db.create_session("child", source="telegram", parent_session_id="root", cwd="/tmp/project")
    db.set_session_title("child", "Cross-vendor handoff")
    db.append_message("child", role="user", content="continue here", timestamp=120)
    db.append_message("child", role="assistant", content="current answer", timestamp=130)

    markdown = db.export_handoff_markdown("child", max_messages=3)

    assert "# Session handoff" in markdown
    assert "- Title: Cross-vendor handoff" in markdown
    assert "- Session ID: `child`" in markdown
    assert "- Source: `telegram`" in markdown
    assert "- Working directory: `/tmp/project`" in markdown
    assert "- Last transcript event: 1970-01-01T00:02:10Z" in markdown
    assert "root answer" in markdown
    assert "continue here" in markdown
    assert "current answer" in markdown
    assert "root question" not in markdown


def test_export_handoff_markdown_includes_handoff_state_and_tool_calls(db, monkeypatch):
    db.create_session("sess-1", source="cli")
    db.set_session_title("sess-1", "Tool-rich handoff")
    db.append_message(
        "sess-1",
        role="assistant",
        content="planning",
        tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
        timestamp=200,
    )
    db.append_message(
        "sess-1",
        role="tool",
        tool_name="search",
        tool_call_id="call-1",
        content={"ok": True, "hits": 2},
        timestamp=210,
    )

    monkeypatch.setattr("hermes_state.time.time", lambda: 250.0)
    assert db.request_handoff("sess-1", "discord") is True

    markdown = db.export_handoff_markdown("sess-1")

    assert "- Handoff state: `pending` via `discord`" in markdown
    assert "- Handoff status updated: 1970-01-01T00:04:10Z" in markdown
    assert "- Tool: `search`" in markdown
    assert "- Tool call ID: `call-1`" in markdown
    assert "- Tool calls:" in markdown
    assert '"hits": 2' in markdown


def test_export_handoff_markdown_rejects_invalid_requests(db):
    with pytest.raises(ValueError, match="session not found"):
        db.export_handoff_markdown("missing")

    db.create_session("sess-2", source="cli")
    with pytest.raises(ValueError, match="max_messages"):
        db.export_handoff_markdown("sess-2", max_messages=0)
