"""Testes para agent/cron/unified_scheduler.py — issue #44."""

from __future__ import annotations

import pytest
from datetime import datetime

from agent.cron.unified_scheduler import (
    CronEntry,
    UnifiedScheduler,
    parse_cron_expression,
    _parse_field,
)


# ---------------------------------------------------------------------------
# Testes de parse de campo
# ---------------------------------------------------------------------------

def test_parse_field_star():
    assert _parse_field("*", 0, 5) == [0, 1, 2, 3, 4, 5]


def test_parse_field_value():
    assert _parse_field("30", 0, 59) == [30]


def test_parse_field_range():
    assert _parse_field("1-3", 0, 59) == [1, 2, 3]


def test_parse_field_step():
    assert _parse_field("*/15", 0, 59) == [0, 15, 30, 45]


def test_parse_field_list():
    assert _parse_field("1,15,30", 0, 59) == [1, 15, 30]


def test_parse_field_invalid_step_zero():
    with pytest.raises(ValueError, match="Passo zero"):
        _parse_field("*/0", 0, 59)


# ---------------------------------------------------------------------------
# Testes de parse de expressão completa
# ---------------------------------------------------------------------------

def test_parse_expression_every_minute():
    fields = parse_cron_expression("* * * * *")
    assert len(fields["minute"]) == 60
    assert len(fields["hour"]) == 24
    assert len(fields["month"]) == 12


def test_parse_expression_wrong_fields():
    with pytest.raises(ValueError, match="5 campos"):
        parse_cron_expression("* * * *")  # apenas 4 campos


def test_parse_expression_specific():
    fields = parse_cron_expression("30 9 1 1 0")
    assert fields["minute"] == [30]
    assert fields["hour"] == [9]
    assert fields["day"] == [1]
    assert fields["month"] == [1]
    assert fields["weekday"] == [0]


# ---------------------------------------------------------------------------
# Testes de CronEntry
# ---------------------------------------------------------------------------

def test_cron_entry_defaults():
    entry = CronEntry(id="test", expression="* * * * *", task_fn=lambda: None)
    assert entry.enabled is True
    assert entry.id == "test"


def test_cron_entry_disabled():
    entry = CronEntry(id="off", expression="* * * * *", task_fn=lambda: None, enabled=False)
    assert entry.enabled is False


# ---------------------------------------------------------------------------
# Testes de UnifiedScheduler
# ---------------------------------------------------------------------------

def test_scheduler_add_and_list():
    s = UnifiedScheduler()
    entry = CronEntry(id="job1", expression="0 9 * * *", task_fn=lambda: None)
    s.add(entry)
    jobs = s.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "job1"


def test_scheduler_add_replaces_same_id():
    s = UnifiedScheduler()
    e1 = CronEntry(id="job", expression="0 9 * * *", task_fn=lambda: None)
    e2 = CronEntry(id="job", expression="0 10 * * *", task_fn=lambda: None)
    s.add(e1)
    s.add(e2)
    jobs = s.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].expression == "0 10 * * *"


def test_scheduler_remove():
    s = UnifiedScheduler()
    entry = CronEntry(id="to_remove", expression="* * * * *", task_fn=lambda: None)
    s.add(entry)
    s.remove("to_remove")
    assert s.list_jobs() == []


def test_scheduler_remove_missing_raises():
    s = UnifiedScheduler()
    with pytest.raises(KeyError, match="não encontrado"):
        s.remove("ghost")


def test_scheduler_add_invalid_expression_raises():
    s = UnifiedScheduler()
    with pytest.raises(ValueError):
        s.add(CronEntry(id="bad", expression="BAD EXPR", task_fn=lambda: None))


# ---------------------------------------------------------------------------
# Testes de get_next_run
# ---------------------------------------------------------------------------

def test_get_next_run_every_minute():
    """Com '* * * * *' o próximo disparo deve ser exatamente 1 min após 'after'."""
    s = UnifiedScheduler()
    entry = CronEntry(id="ev", expression="* * * * *", task_fn=lambda: None)
    s.add(entry)
    ref = datetime(2025, 6, 15, 12, 30, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 6, 15, 12, 31, 0)


def test_get_next_run_daily_9am():
    """'0 9 * * *' dispara às 09:00 do dia seguinte se já passamos das 9 h."""
    s = UnifiedScheduler()
    entry = CronEntry(id="daily", expression="0 9 * * *", task_fn=lambda: None)
    s.add(entry)
    # 2025-06-15 às 10:00 → próximo é 2025-06-16 às 09:00
    ref = datetime(2025, 6, 15, 10, 0, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 6, 16, 9, 0, 0)


def test_get_next_run_specific_minute():
    """'30 * * * *' deve disparar nos :30 de qualquer hora."""
    s = UnifiedScheduler()
    entry = CronEntry(id="halfhour", expression="30 * * * *", task_fn=lambda: None)
    s.add(entry)
    ref = datetime(2025, 1, 1, 0, 0, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 1, 1, 0, 30, 0)


def test_get_next_run_monthly():
    """'0 0 1 * *' dispara no 1º de cada mês à meia-noite."""
    s = UnifiedScheduler()
    entry = CronEntry(id="monthly", expression="0 0 1 * *", task_fn=lambda: None)
    s.add(entry)
    ref = datetime(2025, 3, 15, 0, 0, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 4, 1, 0, 0, 0)


def test_get_next_run_step_expression():
    """'*/15 * * * *' — a cada 15 minutos."""
    s = UnifiedScheduler()
    entry = CronEntry(id="quarter", expression="*/15 * * * *", task_fn=lambda: None)
    s.add(entry)
    ref = datetime(2025, 1, 1, 0, 1, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 1, 1, 0, 15, 0)


def test_get_next_run_list_minutes():
    """'0,30 * * * *' — nos :00 e :30 de cada hora."""
    s = UnifiedScheduler()
    entry = CronEntry(id="bihr", expression="0,30 * * * *", task_fn=lambda: None)
    s.add(entry)
    ref = datetime(2025, 1, 1, 0, 5, 0)
    nxt = s.get_next_run(entry, after=ref)
    assert nxt == datetime(2025, 1, 1, 0, 30, 0)
