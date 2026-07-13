from __future__ import annotations

import sqlite3

import pytest

from plugins.simplicio import skill_recall


def _create_catalog(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE skills_registry (
            stable_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            artifact_path TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stable_id TEXT UNIQUE NOT NULL,
            title TEXT,
            content TEXT,
            artifact_path TEXT
        );
        CREATE TABLE skill_load_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    rows = [
        ("diagnose", "wesleysimplicio/engineering/diagnosing-bugs", "Diagnosis loop for hard bugs and performance regressions."),
        ("debug", "systematic-debugging", "Systematic debug process for software bugs."),
        ("tdd", "test-driven-development", "Test driven development with red green refactor."),
        ("design", "wesleysimplicio/engineering/codebase-design", "Deep module architecture and interface design."),
    ]
    for stable_id, name, content in rows:
        connection.execute(
            "INSERT INTO skills_registry(stable_id, skill_name, artifact_path) VALUES(?,?,?)",
            (stable_id, name, f"/skills/{name}/SKILL.md"),
        )
        connection.execute(
            "INSERT INTO memory_items(stable_id, title, content, artifact_path) VALUES(?,?,?,?)",
            (stable_id, name, content, f"/skills/{name}/SKILL.md"),
        )
    connection.commit()
    connection.close()


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "memory.sqlite"
    _create_catalog(path)
    monkeypatch.setattr(skill_recall, "DB_PATH", path)
    skill_recall._catalog.cache_clear()
    yield path
    skill_recall._catalog.cache_clear()


def test_confident_intent_injects_only_the_winner(catalog):
    result = skill_recall._pre_llm_call(
        user_message="diagnosticar bug regressão performance stack trace"
    )
    assert result == {
        "context": "Skill recall: `wesleysimplicio/engineering/diagnosing-bugs`. Load only applicable candidates with skill_view."
    }
    assert "score=" not in result["context"]


def test_trivial_conversation_has_zero_skill_overhead(catalog):
    assert skill_recall._pre_llm_call(user_message="bom dia") is None


def test_missing_database_fails_open(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_recall, "DB_PATH", tmp_path / "missing.sqlite")
    skill_recall._catalog.cache_clear()
    assert skill_recall._pre_llm_call(user_message="diagnosticar bug") is None


def test_disable_switch_skips_recall(catalog, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SKILL_RECALL_DISABLE", "1")
    assert skill_recall._pre_llm_call(user_message="diagnosticar bug") is None


def test_successful_skill_view_records_load_event(catalog):
    skill_recall._post_tool_call(
        tool_name="skill_view",
        args={"name": "test-driven-development"},
        result="success: true",
        session_id="session-1",
        task_id="task-1",
    )
    connection = sqlite3.connect(catalog)
    row = connection.execute(
        "SELECT skill_name, event, detail FROM skill_load_events"
    ).fetchone()
    connection.close()
    assert row[0:2] == ("test-driven-development", "loaded")
    assert "session=session-1" in row[2]


def test_register_exposes_both_hooks():
    hooks = {}

    class Context:
        def register_hook(self, name, callback):
            hooks[name] = callback

    skill_recall.register_skill_recall(Context())
    assert hooks == {
        "pre_llm_call": skill_recall._pre_llm_call,
        "post_tool_call": skill_recall._post_tool_call,
    }


def test_catalog_handle_uses_relative_skill_path_to_avoid_bare_name_collisions():
    assert skill_recall._canonical_skill_handle(
        "simplicio-tasks",
        "/Users/test/.simplicio_agent/skills/simplicio-loop/simplicio-tasks/SKILL.md",
    ) == "simplicio-loop/simplicio-tasks"


def test_standalone_html_css_js_request_uses_no_planner_fast_path(catalog):
    result = skill_recall._pre_llm_call(
        user_message="write a snake game using html, css and js"
    )

    assert result is not None
    context = result["context"]
    assert "Fast-path" in context
    assert "Do not load skills" in context
    assert "`simplicio plan`" in context
    assert "`simplicio run`" in context
