"""Tests for capabilities/career_os/skills/hh_apply/store.py.

Covers:
- get_pending_apply_tasks: empty, filters correctly, respects limit/attempts
- update_action_execution: sets fields, increments attempts
- get_today_apply_count: empty, counts done only
- was_apply_cap_notification_sent_today: False/True/wrong event
- get_hh_vacancy_url: correct URL format
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from capabilities.career_os.skills.hh_apply.store import (
    MAX_ATTEMPTS,
    get_hh_vacancy_url,
    get_pending_apply_tasks,
    get_today_apply_count,
    update_action_execution,
    was_apply_cap_notification_sent_today,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_job(conn: sqlite3.Connection, hh_vacancy_id: str = "123456") -> int:
    cur = conn.execute(
        "INSERT INTO job_raw (raw_text, source, source_message_id, hh_vacancy_id)"
        " VALUES ('text', 'hh', ?, ?)",
        (f"hh_{hh_vacancy_id}", hh_vacancy_id),
    )
    conn.commit()
    return cur.lastrowid


def _insert_action(
    conn: sqlite3.Connection,
    job_id: int,
    action_type: str = "AUTO_APPLY",
    status: str = "pending",
    execution_status: str = None,
    execution_attempts: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO actions (job_raw_id, action_type, status, execution_status, execution_attempts)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, action_type, status, execution_status, execution_attempts),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# get_pending_apply_tasks
# ---------------------------------------------------------------------------


class TestGetPendingApplyTasks:
    def test_returns_empty_on_empty_db(self, db_conn):
        assert get_pending_apply_tasks(db_conn) == []

    def test_returns_auto_apply_pending(self, db_conn):
        job_id = _insert_job(db_conn, "111")
        _insert_action(db_conn, job_id)
        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1
        assert tasks[0]["action_id"] is not None
        assert tasks[0]["hh_vacancy_id"] == "111"

    def test_excludes_approval_required(self, db_conn):
        job_id = _insert_job(db_conn, "222")
        _insert_action(db_conn, job_id, action_type="APPROVAL_REQUIRED")
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_job_without_hh_vacancy_id(self, db_conn):
        """Actions on jobs without hh_vacancy_id cannot be applied via browser."""
        cur = db_conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES ('t', 'hh', 'x1')"
        )
        db_conn.commit()
        job_id = cur.lastrowid
        _insert_action(db_conn, job_id)
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_non_pending_status(self, db_conn):
        """Actions with status=approved/rejected/snoozed are not queued."""
        for status in ("approved", "rejected", "snoozed"):
            job_id = _insert_job(db_conn, f"job_{status}")
            _insert_action(db_conn, job_id, status=status)
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_max_attempts_reached(self, db_conn):
        job_id = _insert_job(db_conn, "777")
        _insert_action(db_conn, job_id, execution_attempts=MAX_ATTEMPTS)
        assert get_pending_apply_tasks(db_conn) == []

    def test_includes_failed_below_max_attempts(self, db_conn):
        job_id = _insert_job(db_conn, "888")
        _insert_action(
            db_conn, job_id, execution_status="failed", execution_attempts=MAX_ATTEMPTS - 1
        )
        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1

    def test_respects_limit(self, db_conn):
        for i in range(5):
            job_id = _insert_job(db_conn, f"lim{i}")
            _insert_action(db_conn, job_id)
        tasks = get_pending_apply_tasks(db_conn, limit=3)
        assert len(tasks) == 3

    def test_includes_cover_letter_when_present(self, db_conn):
        job_id = _insert_job(db_conn, "cl_test")
        action_id = _insert_action(db_conn, job_id)
        db_conn.execute(
            "INSERT INTO cover_letters (job_raw_id, action_id, letter_text, model, prompt_version)"
            " VALUES (?, ?, 'Письмо-тест', 'haiku', 'v1')",
            (job_id, action_id),
        )
        db_conn.commit()
        tasks = get_pending_apply_tasks(db_conn)
        assert tasks[0]["cover_letter"] == "Письмо-тест"

    def test_cover_letter_null_when_absent(self, db_conn):
        job_id = _insert_job(db_conn, "no_cl")
        _insert_action(db_conn, job_id)
        tasks = get_pending_apply_tasks(db_conn)
        assert tasks[0]["cover_letter"] is None


# ---------------------------------------------------------------------------
# update_action_execution
# ---------------------------------------------------------------------------


class TestUpdateActionExecution:
    def test_sets_execution_status(self, db_conn):
        job_id = _insert_job(db_conn, "upd1")
        action_id = _insert_action(db_conn, job_id)
        update_action_execution(db_conn, action_id, execution_status="done")
        db_conn.commit()
        row = db_conn.execute(
            "SELECT execution_status FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["execution_status"] == "done"

    def test_sets_error_field(self, db_conn):
        job_id = _insert_job(db_conn, "upd2")
        action_id = _insert_action(db_conn, job_id)
        update_action_execution(db_conn, action_id, execution_status="failed", error="Timeout")
        db_conn.commit()
        row = db_conn.execute(
            "SELECT execution_error FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["execution_error"] == "Timeout"

    def test_increments_attempts(self, db_conn):
        job_id = _insert_job(db_conn, "upd3")
        action_id = _insert_action(db_conn, job_id, execution_attempts=1)
        update_action_execution(db_conn, action_id, execution_status="failed")
        db_conn.commit()
        row = db_conn.execute(
            "SELECT execution_attempts FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["execution_attempts"] == 2

    def test_sets_applied_at(self, db_conn):
        job_id = _insert_job(db_conn, "upd4")
        action_id = _insert_action(db_conn, job_id)
        ts = "2026-01-15 10:00:00"
        update_action_execution(db_conn, action_id, execution_status="done", applied_at=ts)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT applied_at FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["applied_at"] == ts

    def test_sets_apply_url(self, db_conn):
        job_id = _insert_job(db_conn, "upd5")
        action_id = _insert_action(db_conn, job_id)
        url = "https://hh.ru/vacancy/99999"
        update_action_execution(db_conn, action_id, execution_status="done", apply_url=url)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT hh_apply_url FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["hh_apply_url"] == url


# ---------------------------------------------------------------------------
# get_today_apply_count
# ---------------------------------------------------------------------------


class TestGetTodayApplyCount:
    def test_returns_0_on_empty_db(self, db_conn):
        assert get_today_apply_count(db_conn) == 0

    def test_counts_done_actions(self, db_conn):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(3):
            job_id = _insert_job(db_conn, f"done{i}")
            action_id = _insert_action(db_conn, job_id, execution_status="done")
            db_conn.execute(
                "UPDATE actions SET applied_at = ? WHERE id = ?", (today, action_id)
            )
        db_conn.commit()
        assert get_today_apply_count(db_conn) == 3

    def test_excludes_failed_actions(self, db_conn):
        job_id = _insert_job(db_conn, "fail1")
        _insert_action(db_conn, job_id, execution_status="failed")
        assert get_today_apply_count(db_conn) == 0

    def test_excludes_old_applies(self, db_conn):
        job_id = _insert_job(db_conn, "old1")
        action_id = _insert_action(db_conn, job_id, execution_status="done")
        db_conn.execute(
            "UPDATE actions SET applied_at = '2020-01-01 00:00:00' WHERE id = ?", (action_id,)
        )
        db_conn.commit()
        assert get_today_apply_count(db_conn) == 0


# ---------------------------------------------------------------------------
# was_apply_cap_notification_sent_today
# ---------------------------------------------------------------------------


class TestWasApplyCapNotificationSentToday:
    def test_returns_false_initially(self, db_conn):
        assert was_apply_cap_notification_sent_today(db_conn) is False

    def test_returns_true_after_event(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('apply.cap_reached', '{}', 'test')"
        )
        db_conn.commit()
        assert was_apply_cap_notification_sent_today(db_conn) is True

    def test_different_event_does_not_trigger(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('scoring.cap_reached', '{}', 'test')"
        )
        db_conn.commit()
        assert was_apply_cap_notification_sent_today(db_conn) is False


# ---------------------------------------------------------------------------
# get_hh_vacancy_url
# ---------------------------------------------------------------------------


class TestGetHhVacancyUrl:
    def test_constructs_correct_url(self):
        url = get_hh_vacancy_url("12345678")
        assert url == "https://hh.ru/vacancy/12345678"

    def test_url_contains_vacancy_id(self):
        url = get_hh_vacancy_url("99999")
        assert "99999" in url
        assert url.startswith("https://hh.ru/vacancy/")
