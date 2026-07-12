"""Repositories internos de SessionDB (issue #223).

Extrai acesso a sessões/mensagens em classes isoladas com transações explícitas
e recovery boundary. NÃO reescreve hermes_state.py: este módulo é standalone e
pode ser usado pelo SessionDB como delegação interna sem quebrar a API pública.

O Simplicio Agent continua dono do SQLite/WAL/FTS5; o Runtime nunca recebe
estado conversacional.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, List, Optional


@dataclass
class SessionRecord:
    session_id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MessageRecord:
    rowid: int
    session_id: str
    role: str
    content: str
    created_at: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


class SessionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def save(self, rec: SessionRecord) -> None:
        with self.transaction():
            self._conn.execute(
                "INSERT INTO sessions(session_id, title, created_at, updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
                (rec.session_id, rec.title, rec.created_at, rec.updated_at),
            )

    def load(self, session_id: str) -> Optional[SessionRecord]:
        row = self._conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return SessionRecord(*row)

    def list_all(self) -> List[SessionRecord]:
        return [SessionRecord(*r) for r in self._conn.execute("SELECT session_id, title, created_at, updated_at FROM sessions")]


class MessageRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def append(self, session_id: str, role: str, content: str, created_at: str = "") -> int:
        with self.transaction():
            cur = self._conn.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                (session_id, role, content, created_at),
            )
            return int(cur.lastrowid or 0)

    def by_session(self, session_id: str) -> List[MessageRecord]:
        rows = self._conn.execute(
            "SELECT rowid, session_id, role, content, created_at FROM messages WHERE session_id=? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return [MessageRecord(*r) for r in rows]


def open_store(path: str) -> sqlite3.Connection:
    """Abre SQLite com WAL (padrão do SessionDB) e row factory dict-like."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
