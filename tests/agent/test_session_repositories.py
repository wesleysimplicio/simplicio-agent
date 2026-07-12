"""Testes dos repositories de SessionDB (issue #223)."""
from __future__ import annotations

import os
import tempfile

import pytest

from agent.session_repositories import (
    MessageRecord,
    MessageRepository,
    SessionRecord,
    SessionRepository,
    open_store,
)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "session.db")
        conn = open_store(path)
        sess = SessionRepository(conn)
        sess.init_schema()
        yield conn, sess, MessageRepository(conn)
        conn.close()


def test_session_save_load(store):
    conn, sess, _ = store
    rec = SessionRecord("s1", title="Chat", created_at="t0", updated_at="t0")
    sess.save(rec)
    loaded = sess.load("s1")
    assert loaded is not None
    assert loaded.title == "Chat"
    assert loaded.session_id == "s1"


def test_message_persist(store):
    conn, sess, msg = store
    sess.save(SessionRecord("s1"))
    msg.append("s1", "user", "oi")
    msg.append("s1", "assistant", "ola")
    rows = msg.by_session("s1")
    assert len(rows) == 2
    assert isinstance(rows[0], MessageRecord)
    assert rows[0].role == "user"
    assert rows[1].content == "ola"


def test_recovery_after_crash(store):
    conn, sess, msg = store
    sess.save(SessionRecord("s1", title="Importante"))
    msg.append("s1", "user", "dado critico")
    # simula crash: fecha e reabre o DB (nova conexão, mesmo arquivo)
    path = conn.execute("PRAGMA database_list").fetchall()
    db_path = path[0][2]
    conn.close()
    reopened = open_store(db_path)
    reopened.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    r_sess = SessionRepository(reopened)
    r_msg = MessageRepository(reopened)
    assert r_sess.load("s1").title == "Importante"
    assert r_msg.by_session("s1")[0].content == "dado critico"
    reopened.close()
