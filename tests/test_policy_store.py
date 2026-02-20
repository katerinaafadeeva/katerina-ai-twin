"""Tests for capabilities/career_os/skills/apply_policy/store.py.

Covers:
- get_policy: reads row id=1, returns defaults if missing
- get_today_auto_count: counts AUTO_QUEUE + AUTO_APPLY (both), ignores IGNORE/HOLD
- get_today_hold_count: counts only HOLD
- was_hold_notification_sent_today: checks events table for policy.hold_summary
- save_action: persists all fields including extended migration-004 columns
"""

import sqlite3

import pytest

from capabilities.career_os.skills.apply_policy.engine import ActionType, PolicyDecision
from capabilities.career_os.skills.apply_policy.store import (
    get_policy,
    get_today_auto_count,
    get_today_hold_count,
    save_action,
    was_hold_notification_sent_today,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_job(conn: sqlite3.Connection, source: str = "tg") -> int:
    """Insert a minimal job_raw row and return its id."""
    cursor = conn.execute(
        "INSERT INTO job_raw (raw_text, source) VALUES (?, ?)",
        ("Sample vacancy text", source),
    )
    conn.commit()
    return cursor.lastrowid


def _make_decision(action_type: ActionType, reason: str = "test reason") -> PolicyDecision:
    return PolicyDecision(action_type=action_type, reason=reason)


def _insert_action(conn: sqlite3.Connection, job_raw_id: int, action_type: str) -> None:
    """Insert an action row directly (bypassing save_action) for count tests."""
    conn.execute(
        "INSERT INTO actions (job_raw_id, action_type, status) VALUES (?, ?, 'pending')",
        (job_raw_id, action_type),
    )
    conn.commit()


def _insert_event(conn: sqlite3.Connection, event_name: str) -> None:
    """Insert an event row directly."""
    conn.execute(
        "INSERT INTO events (event_name, payload_json) VALUES (?, '{}')",
        (event_name,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get_policy
# ---------------------------------------------------------------------------


class TestGetPolicy:
    def test_returns_row_1(self, db_conn):
        """Default migration seeds row id=1; get_policy returns it."""
        policy = get_policy(db_conn)
        assert policy["id"] == 1
        assert policy["threshold_low"] == 5
        assert policy["threshold_high"] == 7
        assert policy["daily_limit"] == 40

    def test_custom_values(self, db_conn):
        """After updating policy row, get_policy returns updated values."""
        db_conn.execute(
            "UPDATE policy SET threshold_low=4, threshold_high=8, daily_limit=20 WHERE id=1"
        )
        db_conn.commit()
        policy = get_policy(db_conn)
        assert policy["threshold_low"] == 4
        assert policy["threshold_high"] == 8
        assert policy["daily_limit"] == 20

    def test_defaults_if_missing(self, db_conn):
        """When policy row is absent, function returns hardcoded defaults."""
        db_conn.execute("DELETE FROM policy WHERE id=1")
        db_conn.commit()
        policy = get_policy(db_conn)
        assert policy["threshold_low"] == 5
        assert policy["threshold_high"] == 7
        assert policy["daily_limit"] == 40


# ---------------------------------------------------------------------------
# get_today_auto_count
# ---------------------------------------------------------------------------


class TestGetTodayAutoCount:
    def test_empty(self, db_conn):
        assert get_today_auto_count(db_conn) == 0

    def test_counts_auto_apply(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.AUTO_APPLY.value)
        assert get_today_auto_count(db_conn) == 1

    def test_counts_auto_queue(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.AUTO_QUEUE.value)
        assert get_today_auto_count(db_conn) == 1

    def test_counts_both_types(self, db_conn):
        """AUTO_QUEUE and AUTO_APPLY both consume the daily limit."""
        job1 = _insert_job(db_conn)
        job2 = _insert_job(db_conn)
        _insert_action(db_conn, job1, ActionType.AUTO_APPLY.value)
        _insert_action(db_conn, job2, ActionType.AUTO_QUEUE.value)
        assert get_today_auto_count(db_conn) == 2

    def test_ignores_hold(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.HOLD.value)
        assert get_today_auto_count(db_conn) == 0

    def test_ignores_ignore(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.IGNORE.value)
        assert get_today_auto_count(db_conn) == 0

    def test_ignores_approval_required(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.APPROVAL_REQUIRED.value)
        assert get_today_auto_count(db_conn) == 0

    def test_multiple_auto_apply(self, db_conn):
        for _ in range(5):
            job_id = _insert_job(db_conn)
            _insert_action(db_conn, job_id, ActionType.AUTO_APPLY.value)
        assert get_today_auto_count(db_conn) == 5


# ---------------------------------------------------------------------------
# get_today_hold_count
# ---------------------------------------------------------------------------


class TestGetTodayHoldCount:
    def test_empty(self, db_conn):
        assert get_today_hold_count(db_conn) == 0

    def test_counts_hold(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.HOLD.value)
        assert get_today_hold_count(db_conn) == 1

    def test_ignores_auto_queue(self, db_conn):
        job_id = _insert_job(db_conn)
        _insert_action(db_conn, job_id, ActionType.AUTO_QUEUE.value)
        assert get_today_hold_count(db_conn) == 0

    def test_multiple_holds(self, db_conn):
        for _ in range(3):
            job_id = _insert_job(db_conn)
            _insert_action(db_conn, job_id, ActionType.HOLD.value)
        assert get_today_hold_count(db_conn) == 3


# ---------------------------------------------------------------------------
# was_hold_notification_sent_today
# ---------------------------------------------------------------------------


class TestWasHoldNotificationSentToday:
    def test_false_when_no_events(self, db_conn):
        assert was_hold_notification_sent_today(db_conn) is False

    def test_true_after_hold_summary_event(self, db_conn):
        _insert_event(db_conn, "policy.hold_summary")
        assert was_hold_notification_sent_today(db_conn) is True

    def test_false_for_other_event(self, db_conn):
        _insert_event(db_conn, "vacancy.scored")
        assert was_hold_notification_sent_today(db_conn) is False

    def test_true_only_for_exact_event_name(self, db_conn):
        _insert_event(db_conn, "policy.hold_summary_extra")
        assert was_hold_notification_sent_today(db_conn) is False


# ---------------------------------------------------------------------------
# save_action
# ---------------------------------------------------------------------------


class TestSaveAction:
    def test_returns_int_rowid(self, db_conn):
        """save_action must return int, not tuple — guards against trailing-comma regression."""
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.AUTO_QUEUE, "test reason")
        rowid = save_action(db_conn, job_id, decision, score=5)
        db_conn.commit()
        assert isinstance(rowid, int), f"expected int, got {type(rowid)} — trailing comma bug?"
        assert rowid > 0

    def test_persists_action_type(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.AUTO_APPLY, "автоотклик HH 1/40")
        save_action(db_conn, job_id, decision, score=6)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["action_type"] == "AUTO_APPLY"

    def test_persists_score_and_reason(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.HOLD, "дневной лимит исчерпан")
        save_action(db_conn, job_id, decision, score=5)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["score"] == 5
        assert row["reason"] == "дневной лимит исчерпан"

    def test_persists_actor_default(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.IGNORE, "ниже порога")
        save_action(db_conn, job_id, decision, score=3)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["actor"] == "policy_engine"

    def test_persists_custom_actor(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.AUTO_QUEUE, "в очередь")
        save_action(db_conn, job_id, decision, score=5, actor="test_actor")
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["actor"] == "test_actor"

    def test_persists_correlation_id(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.APPROVAL_REQUIRED, "высокий приоритет")
        cid = "test-correlation-uuid"
        save_action(db_conn, job_id, decision, score=8, correlation_id=cid)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["correlation_id"] == cid

    def test_status_is_pending(self, db_conn):
        job_id = _insert_job(db_conn)
        decision = _make_decision(ActionType.AUTO_QUEUE, "в очередь")
        save_action(db_conn, job_id, decision, score=5)
        db_conn.commit()
        row = db_conn.execute(
            "SELECT * FROM actions WHERE job_raw_id = ?", (job_id,)
        ).fetchone()
        assert row["status"] == "pending"

    def test_all_action_types_can_be_saved(self, db_conn):
        for action_type in ActionType:
            job_id = _insert_job(db_conn)
            decision = _make_decision(action_type, f"reason for {action_type.value}")
            rowid = save_action(db_conn, job_id, decision, score=5)
            db_conn.commit()
            assert rowid > 0
