"""Tests for capabilities/career_os/skills/control_plane/store.py.

Covers:
- get_action_by_id: missing, existing
- update_action_status: pending→approved/rejected/snoozed, invalid transitions,
  idempotent guard, updated_at set
- get_today_summary: empty DB, mixed actions
- get_pending_approvals: empty, correct filtering
- get_policy_display: defaults, with actions
"""

import sqlite3

import pytest

from capabilities.career_os.skills.apply_policy.engine import ActionType, PolicyDecision
from capabilities.career_os.skills.apply_policy.store import save_action
from capabilities.career_os.skills.control_plane.store import (
    get_action_by_id,
    get_pending_approvals,
    get_policy_display,
    get_today_summary,
    update_action_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APPROVAL_DECISION = PolicyDecision(
    action_type=ActionType.APPROVAL_REQUIRED,
    reason="Оценка 8/10 — требует одобрения оператора",
)
_IGNORE_DECISION = PolicyDecision(
    action_type=ActionType.IGNORE,
    reason="Оценка 2/10 — ниже порога",
)
_AUTO_QUEUE_DECISION = PolicyDecision(
    action_type=ActionType.AUTO_QUEUE,
    reason="Оценка 5/10 — авто-очередь (1/40)",
)
_AUTO_APPLY_DECISION = PolicyDecision(
    action_type=ActionType.AUTO_APPLY,
    reason="Оценка 6/10 — автоотклик HH (2/40)",
)
_HOLD_DECISION = PolicyDecision(
    action_type=ActionType.HOLD,
    reason="Лимит достигнут (40/40)",
)


def _insert_job_raw(conn: sqlite3.Connection, source: str = "tg") -> int:
    """Insert a minimal job_raw row, return its id."""
    cursor = conn.execute(
        "INSERT INTO job_raw (raw_text, source) VALUES (?, ?)",
        ("Vacancy text", source),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_action(
    conn: sqlite3.Connection,
    action_type: str = "APPROVAL_REQUIRED",
    status: str = "pending",
    score: int = 8,
) -> int:
    """Insert an action row directly (bypasses save_action for status control)."""
    cursor = conn.execute(
        """
        INSERT INTO actions (job_raw_id, action_type, status, score, reason, actor)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            _insert_job_raw(conn),
            action_type,
            status,
            score,
            f"Reason for {action_type}",
            "policy_engine",
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# get_action_by_id
# ---------------------------------------------------------------------------


class TestGetActionById:
    def test_returns_none_for_missing_id(self, db_conn):
        result = get_action_by_id(db_conn, 9999)
        assert result is None

    def test_returns_dict_for_existing(self, db_conn):
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")
        result = get_action_by_id(db_conn, action_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["id"] == action_id
        assert result["action_type"] == "APPROVAL_REQUIRED"
        assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# update_action_status
# ---------------------------------------------------------------------------


class TestUpdateActionStatus:
    def test_approve_pending_action(self, db_conn):
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")
        result = update_action_status(db_conn, action_id, "approved")
        assert result is True
        row = get_action_by_id(db_conn, action_id)
        assert row["status"] == "approved"

    def test_reject_pending_action(self, db_conn):
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")
        result = update_action_status(db_conn, action_id, "rejected")
        assert result is True
        row = get_action_by_id(db_conn, action_id)
        assert row["status"] == "rejected"

    def test_snooze_pending_action(self, db_conn):
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")
        result = update_action_status(db_conn, action_id, "snoozed")
        assert result is True
        row = get_action_by_id(db_conn, action_id)
        assert row["status"] == "snoozed"

    def test_cannot_approve_already_approved(self, db_conn):
        action_id = _insert_action(db_conn, status="approved")
        result = update_action_status(db_conn, action_id, "approved")
        assert result is False

    def test_cannot_approve_rejected(self, db_conn):
        action_id = _insert_action(db_conn, status="rejected")
        result = update_action_status(db_conn, action_id, "approved")
        assert result is False

    def test_cannot_reject_snoozed(self, db_conn):
        action_id = _insert_action(db_conn, status="snoozed")
        result = update_action_status(db_conn, action_id, "rejected")
        assert result is False

    def test_only_pending_transitions_allowed(self, db_conn):
        for status in ("approved", "rejected", "snoozed"):
            action_id = _insert_action(db_conn, status=status)
            assert update_action_status(db_conn, action_id, "approved") is False

    def test_updated_at_is_set_on_transition(self, db_conn):
        action_id = _insert_action(db_conn, status="pending")
        before = get_action_by_id(db_conn, action_id)
        assert before["updated_at"] is None

        update_action_status(db_conn, action_id, "approved")
        db_conn.commit()

        after = get_action_by_id(db_conn, action_id)
        assert after["updated_at"] is not None

    def test_double_click_idempotent(self, db_conn):
        """Second attempt on an already-transitioned action must return False (not crash)."""
        action_id = _insert_action(db_conn, status="pending")
        first = update_action_status(db_conn, action_id, "approved")
        db_conn.commit()
        second = update_action_status(db_conn, action_id, "approved")
        assert first is True
        assert second is False


# ---------------------------------------------------------------------------
# get_today_summary
# ---------------------------------------------------------------------------


class TestGetTodaySummary:
    def test_empty_db(self, db_conn):
        s = get_today_summary(db_conn)
        assert s["total_ingested"] == 0
        assert s["total_scored"] == 0
        assert s["auto_count"] == 0
        assert all(v == 0 for v in s["by_action_type"].values())
        assert all(v == 0 for v in s["by_status"].values())

    def test_with_mixed_actions(self, db_conn):
        # Insert: 1 IGNORE, 1 AUTO_QUEUE, 1 APPROVAL_REQUIRED (pending), 1 approved
        _insert_action(db_conn, action_type="IGNORE", status="pending", score=2)
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending", score=8)
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending", score=9)
        update_action_status(db_conn, action_id, "approved")
        db_conn.commit()

        s = get_today_summary(db_conn)

        assert s["by_action_type"]["IGNORE"] == 1
        assert s["by_action_type"]["AUTO_QUEUE"] == 1
        assert s["by_action_type"]["APPROVAL_REQUIRED"] == 2

        assert s["by_status"]["pending"] == 3
        assert s["by_status"]["approved"] == 1

    def test_auto_count_counts_auto_queue_and_auto_apply(self, db_conn):
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="AUTO_APPLY", status="pending", score=6)
        _insert_action(db_conn, action_type="HOLD", status="pending", score=5)
        s = get_today_summary(db_conn)
        assert s["auto_count"] == 2  # HOLD not counted

    def test_summary_keys_present(self, db_conn):
        s = get_today_summary(db_conn)
        required_keys = {
            "total_ingested", "total_scored", "by_action_type",
            "by_status", "decisions_today", "auto_count", "daily_limit", "remaining",
        }
        assert required_keys.issubset(s.keys())

    def test_decisions_today_counts_all_action_types(self, db_conn):
        """decisions_today = all actions, not just AUTO_QUEUE/AUTO_APPLY."""
        _insert_action(db_conn, action_type="IGNORE", status="pending", score=2)
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="AUTO_APPLY", status="pending", score=6)
        _insert_action(db_conn, action_type="HOLD", status="pending", score=5)
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending", score=8)
        s = get_today_summary(db_conn)
        assert s["decisions_today"] == 5  # all 5 action types counted
        assert s["auto_count"] == 2       # only AUTO_QUEUE + AUTO_APPLY

    def test_decisions_today_empty_db(self, db_conn):
        s = get_today_summary(db_conn)
        assert s["decisions_today"] == 0

    def test_remaining_is_daily_limit_minus_auto_count(self, db_conn):
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="AUTO_APPLY", status="pending", score=6)
        s = get_today_summary(db_conn)
        assert s["remaining"] == s["daily_limit"] - 2


# ---------------------------------------------------------------------------
# get_pending_approvals
# ---------------------------------------------------------------------------


class TestGetPendingApprovals:
    def test_empty(self, db_conn):
        result = get_pending_approvals(db_conn)
        assert result == []

    def test_returns_only_pending_approval_required(self, db_conn):
        _insert_action(db_conn, action_type="IGNORE", status="pending")
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending")
        action_id = _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")

        result = get_pending_approvals(db_conn)
        assert len(result) == 1
        assert result[0]["id"] == action_id

    def test_excludes_approved(self, db_conn):
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="approved")
        result = get_pending_approvals(db_conn)
        assert result == []

    def test_excludes_rejected_and_snoozed(self, db_conn):
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="rejected")
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="snoozed")
        result = get_pending_approvals(db_conn)
        assert result == []

    def test_result_contains_required_keys(self, db_conn):
        _insert_action(db_conn, action_type="APPROVAL_REQUIRED", status="pending")
        result = get_pending_approvals(db_conn)
        assert len(result) == 1
        row = result[0]
        for key in ("id", "job_raw_id", "score", "reason", "created_at"):
            assert key in row, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_policy_display
# ---------------------------------------------------------------------------


class TestGetPolicyDisplay:
    def test_defaults(self, db_conn):
        p = get_policy_display(db_conn)
        assert p["threshold_low"] == 5
        assert p["threshold_high"] == 7
        assert p["daily_limit"] == 40
        assert p["today_auto_count"] == 0
        assert p["remaining"] == 40

    def test_with_actions(self, db_conn):
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="AUTO_APPLY", status="pending", score=6)
        p = get_policy_display(db_conn)
        assert p["today_auto_count"] == 2
        assert p["remaining"] == 38

    def test_remaining_never_negative(self, db_conn):
        """remaining is capped at 0 even if auto_count somehow exceeds daily_limit."""
        # Override daily_limit to 1 to force this scenario
        db_conn.execute(
            "INSERT OR REPLACE INTO policy (id, threshold_low, threshold_high, daily_limit) VALUES (1, 5, 7, 1)"
        )
        db_conn.commit()
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        _insert_action(db_conn, action_type="AUTO_QUEUE", status="pending", score=5)
        p = get_policy_display(db_conn)
        assert p["remaining"] == 0
