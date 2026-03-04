"""Tests for capabilities/career_os/skills/hh_apply/store.py.

Schema: apply_runs separates execution log from actions (decision log).

Covers:
- get_pending_apply_tasks: empty, filters correctly, respects limit/attempts
- save_apply_run: inserts row, idempotent on duplicate (UNIQUE action+attempt)
- get_today_apply_count: empty, counts done only, excludes old dates
- get_attempt_count: zero when no runs, counts all statuses
- was_apply_cap_notification_sent_today: False/True/wrong event
- get_hh_vacancy_url: correct URL format
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from capabilities.career_os.skills.hh_apply.store import (
    MAX_ATTEMPTS,
    get_attempt_count,
    get_hh_vacancy_url,
    get_pending_apply_tasks,
    get_today_apply_count,
    save_apply_run,
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
) -> int:
    cur = conn.execute(
        "INSERT INTO actions (job_raw_id, action_type, status) VALUES (?, ?, ?)",
        (job_id, action_type, status),
    )
    conn.commit()
    return cur.lastrowid


def _insert_run(
    conn: sqlite3.Connection,
    action_id: int,
    attempt: int = 1,
    status: str = "done",
    finished_at: str = None,
) -> int:
    today = finished_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return save_apply_run(conn, action_id=action_id, attempt=attempt, status=status, finished_at=today)


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
        assert tasks[0]["hh_vacancy_id"] == "111"
        assert tasks[0]["attempt_count"] == 0
        assert "vacancy_text" in tasks[0]  # raw_text exposed for JIT letter generation

    def test_excludes_approval_required(self, db_conn):
        job_id = _insert_job(db_conn, "222")
        _insert_action(db_conn, job_id, action_type="APPROVAL_REQUIRED")
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_job_without_hh_vacancy_id(self, db_conn):
        cur = db_conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES ('t', 'hh', 'x1')"
        )
        db_conn.commit()
        _insert_action(db_conn, cur.lastrowid)
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_non_pending_action_status(self, db_conn):
        for status in ("approved", "rejected", "snoozed"):
            job_id = _insert_job(db_conn, f"job_{status}")
            _insert_action(db_conn, job_id, status=status)
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_already_successfully_applied(self, db_conn):
        """Action with a done apply_run must not be re-queued."""
        job_id = _insert_job(db_conn, "done_one")
        action_id = _insert_action(db_conn, job_id)
        _insert_run(db_conn, action_id, attempt=1, status="done")
        db_conn.commit()
        assert get_pending_apply_tasks(db_conn) == []

    def test_excludes_max_attempts_reached(self, db_conn):
        """Action with MAX_ATTEMPTS failed runs must not be re-queued."""
        job_id = _insert_job(db_conn, "max_att")
        action_id = _insert_action(db_conn, job_id)
        for i in range(1, MAX_ATTEMPTS + 1):
            _insert_run(db_conn, action_id, attempt=i, status="failed")
        db_conn.commit()
        assert get_pending_apply_tasks(db_conn) == []

    def test_includes_failed_below_max_attempts(self, db_conn):
        """Action with < MAX_ATTEMPTS failed runs should be retried."""
        job_id = _insert_job(db_conn, "retry_me")
        action_id = _insert_action(db_conn, job_id)
        for i in range(1, MAX_ATTEMPTS):
            _insert_run(db_conn, action_id, attempt=i, status="failed")
        db_conn.commit()
        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1
        assert tasks[0]["attempt_count"] == MAX_ATTEMPTS - 1

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

    def test_excludes_manual_required_status(self, db_conn):
        """manual_required should not be retried."""
        job_id = _insert_job(db_conn, "manual_stop")
        action_id = _insert_action(db_conn, job_id)
        _insert_run(db_conn, action_id, attempt=1, status="manual_required")
        db_conn.commit()
        assert get_pending_apply_tasks(db_conn) == []

    def test_cover_letter_fallback_by_job_raw_id(self, db_conn):
        """New AUTO_APPLY action inherits cover letter from previous action for same job.

        Scenario (mirrors Bug 1 from production):
          - job_raw_id=X, old action_id=OLD has cover letter
          - new action_id=NEW for same job has no cover letter row
          - get_pending_apply_tasks must return the letter via job_raw_id fallback
        """
        job_id = _insert_job(db_conn, "fallback_test")
        # Old APPROVAL_REQUIRED action that already has a cover letter
        # (realistic: scored → APPROVAL_REQUIRED → operator approved → AUTO_APPLY created)
        old_action_id = _insert_action(db_conn, job_id, action_type="APPROVAL_REQUIRED", status="approved")
        db_conn.execute(
            "INSERT INTO cover_letters (job_raw_id, action_id, letter_text, model, prompt_version)"
            " VALUES (?, ?, 'Inherited letter', 'haiku', 'v1')",
            (job_id, old_action_id),
        )
        db_conn.commit()
        # New pending AUTO_APPLY action — no cover_letter row of its own
        _insert_action(db_conn, job_id, action_type="AUTO_APPLY", status="pending")
        db_conn.commit()

        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1
        assert tasks[0]["cover_letter"] == "Inherited letter"

    def test_cover_letter_action_id_takes_priority(self, db_conn):
        """Direct action_id match wins over job_raw_id fallback."""
        job_id = _insert_job(db_conn, "priority_test")
        action_id = _insert_action(db_conn, job_id)
        # Cover letter for a different old action (job_raw_id match only)
        # Uses APPROVAL_REQUIRED to avoid UNIQUE constraint with the AUTO_APPLY action above
        old_action_id = db_conn.execute(
            "INSERT INTO actions (job_raw_id, action_type, status) VALUES (?, 'APPROVAL_REQUIRED', 'approved')",
            (job_id,),
        ).lastrowid
        db_conn.execute(
            "INSERT INTO cover_letters (job_raw_id, action_id, letter_text, model, prompt_version)"
            " VALUES (?, ?, 'Old letter', 'haiku', 'v1')",
            (job_id, old_action_id),
        )
        # Cover letter directly for current action (should win)
        db_conn.execute(
            "INSERT INTO cover_letters (job_raw_id, action_id, letter_text, model, prompt_version)"
            " VALUES (?, ?, 'Direct letter', 'haiku', 'v1')",
            (job_id, action_id),
        )
        db_conn.commit()

        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1
        assert tasks[0]["cover_letter"] == "Direct letter"


# ---------------------------------------------------------------------------
# save_apply_run
# ---------------------------------------------------------------------------


class TestSaveApplyRun:
    def test_inserts_and_returns_rowid(self, db_conn):
        job_id = _insert_job(db_conn, "sv1")
        action_id = _insert_action(db_conn, job_id)
        rowid = save_apply_run(db_conn, action_id=action_id, attempt=1, status="done")
        db_conn.commit()
        assert rowid > 0

    def test_stores_status_and_error(self, db_conn):
        job_id = _insert_job(db_conn, "sv2")
        action_id = _insert_action(db_conn, job_id)
        save_apply_run(db_conn, action_id=action_id, attempt=1, status="failed", error="Timeout")
        db_conn.commit()
        row = db_conn.execute(
            "SELECT status, error FROM apply_runs WHERE action_id = ?", (action_id,)
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "Timeout"

    def test_idempotent_on_duplicate_attempt(self, db_conn):
        """INSERT OR IGNORE — same (action_id, attempt) ignored on second call."""
        job_id = _insert_job(db_conn, "sv3")
        action_id = _insert_action(db_conn, job_id)
        r1 = save_apply_run(db_conn, action_id=action_id, attempt=1, status="done")
        db_conn.commit()
        r2 = save_apply_run(db_conn, action_id=action_id, attempt=1, status="done")
        db_conn.commit()
        assert r1 > 0
        assert r2 == 0  # ignored

    def test_allows_multiple_attempts(self, db_conn):
        """Different attempt numbers for same action are all stored."""
        job_id = _insert_job(db_conn, "sv4")
        action_id = _insert_action(db_conn, job_id)
        save_apply_run(db_conn, action_id=action_id, attempt=1, status="failed")
        save_apply_run(db_conn, action_id=action_id, attempt=2, status="done")
        db_conn.commit()
        count = db_conn.execute(
            "SELECT COUNT(*) FROM apply_runs WHERE action_id = ?", (action_id,)
        ).fetchone()[0]
        assert count == 2

    def test_stores_apply_url(self, db_conn):
        job_id = _insert_job(db_conn, "sv5")
        action_id = _insert_action(db_conn, job_id)
        url = "https://hh.ru/vacancy/99999"
        save_apply_run(db_conn, action_id=action_id, attempt=1, status="done", apply_url=url)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT apply_url FROM apply_runs WHERE action_id = ?", (action_id,)
        ).fetchone()
        assert row["apply_url"] == url


# ---------------------------------------------------------------------------
# get_today_apply_count
# ---------------------------------------------------------------------------


class TestGetTodayApplyCount:
    def test_returns_0_on_empty_db(self, db_conn):
        assert get_today_apply_count(db_conn) == 0

    def test_counts_done_runs_today(self, db_conn):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(3):
            job_id = _insert_job(db_conn, f"done{i}")
            action_id = _insert_action(db_conn, job_id)
            save_apply_run(db_conn, action_id=action_id, attempt=1, status="done", finished_at=today)
        db_conn.commit()
        assert get_today_apply_count(db_conn) == 3

    def test_excludes_failed_runs(self, db_conn):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        job_id = _insert_job(db_conn, "fail1")
        action_id = _insert_action(db_conn, job_id)
        save_apply_run(db_conn, action_id=action_id, attempt=1, status="failed", finished_at=today)
        db_conn.commit()
        assert get_today_apply_count(db_conn) == 0

    def test_excludes_old_runs(self, db_conn):
        job_id = _insert_job(db_conn, "old1")
        action_id = _insert_action(db_conn, job_id)
        save_apply_run(
            db_conn, action_id=action_id, attempt=1,
            status="done", finished_at="2020-01-01 00:00:00"
        )
        db_conn.commit()
        assert get_today_apply_count(db_conn) == 0


# ---------------------------------------------------------------------------
# get_attempt_count
# ---------------------------------------------------------------------------


class TestGetAttemptCount:
    def test_returns_0_when_no_runs(self, db_conn):
        job_id = _insert_job(db_conn, "ac1")
        action_id = _insert_action(db_conn, job_id)
        assert get_attempt_count(db_conn, action_id) == 0

    def test_counts_all_statuses(self, db_conn):
        job_id = _insert_job(db_conn, "ac2")
        action_id = _insert_action(db_conn, job_id)
        save_apply_run(db_conn, action_id=action_id, attempt=1, status="failed")
        save_apply_run(db_conn, action_id=action_id, attempt=2, status="done")
        db_conn.commit()
        assert get_attempt_count(db_conn, action_id) == 2


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
