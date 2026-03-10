"""Tests for control_plane handler utilities (unit tests, no real Telegram).

Tests callback_data parsing, is_callback_authorized, and approve flow logic.
"""

import asyncio
import sqlite3
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We import the private helper directly for unit testing.
from capabilities.career_os.skills.control_plane.handlers import _parse_callback
from capabilities.career_os.skills.control_plane.store import update_action_status
from capabilities.career_os.skills.hh_apply.store import get_pending_apply_tasks


class TestParseCallback:
    def test_parse_approve_callback(self):
        result = _parse_callback("approve:42")
        assert result == ("approve", 42)

    def test_parse_reject_callback(self):
        result = _parse_callback("reject:7")
        assert result == ("reject", 7)

    def test_parse_snooze_callback(self):
        result = _parse_callback("snooze:100")
        assert result == ("snooze", 100)

    def test_parse_invalid_action(self):
        """Unknown action string must return None."""
        result = _parse_callback("delete:5")
        assert result is None

    def test_parse_missing_action_id(self):
        """Missing colon → no valid split → None."""
        result = _parse_callback("approve")
        assert result is None

    def test_parse_empty_string(self):
        result = _parse_callback("")
        assert result is None

    def test_parse_non_integer_id(self):
        """Non-integer action_id must return None (not raise)."""
        result = _parse_callback("approve:abc")
        assert result is None

    def test_parse_negative_id(self):
        """Negative integer is technically valid — parses correctly."""
        result = _parse_callback("approve:-1")
        assert result == ("approve", -1)

    def test_parse_large_id(self):
        result = _parse_callback("reject:999999")
        assert result == ("reject", 999999)

    def test_parse_extra_colons(self):
        """Extra colons in callback_data — split(maxsplit=1) keeps remainder as id_str."""
        result = _parse_callback("approve:1:extra")
        # "1:extra" is not a valid int → None
        assert result is None

    def test_parse_none_input(self):
        """Handles None gracefully (e.g. callback.data is None)."""
        result = _parse_callback(None)
        assert result is None


# ---------------------------------------------------------------------------
# Integration test documentation
# ---------------------------------------------------------------------------
# The following scenarios require integration testing with a real or mocked
# aiogram bot (aiogram's CallbackQuery cannot be easily instantiated in unit tests
# without wiring the full dispatcher):
#
# - handle_approval_callback: unauthorized sender → "Нет доступа" answer
# - handle_approval_callback: malformed callback_data → "Неверный формат"
# - handle_approval_callback: action not found → "Действие не найдено"
# - handle_approval_callback: action_type != APPROVAL_REQUIRED → appropriate answer
# - handle_approval_callback: successful approve/reject/snooze → status updated in DB,
#   event emitted, message edited, keyboard removed, callback.answer() called
# - handle_approval_callback: double-click protection → "Уже обработано"
# - cmd_today: unauthorized → no response
# - cmd_today: authorized → returns summary text
# - cmd_limits: returns policy thresholds text
# - cmd_stats: returns summary + pending approvals list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_approval_required_action(conn: sqlite3.Connection) -> int:
    """Insert a minimal APPROVAL_REQUIRED + pending action, return action_id."""
    cur = conn.execute(
        "INSERT INTO job_raw (raw_text, source, hh_vacancy_id) VALUES ('text', 'hh', 'hh_test_1')"
    )
    conn.commit()
    job_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO actions (job_raw_id, action_type, status, score, reason, actor)"
        " VALUES (?, 'APPROVAL_REQUIRED', 'pending', 8, 'Оценка 8/10', 'policy_engine')",
        (job_id,),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# TASK-4: Approve → Apply flow
# ---------------------------------------------------------------------------


class TestApproveFlow:
    def test_approve_callback_updates_action_status(self, db_conn):
        """Approving an action transitions its status to 'approved' in DB."""
        action_id = _insert_approval_required_action(db_conn)
        updated = update_action_status(db_conn, action_id, "approved", actor="operator")
        db_conn.commit()

        assert updated is True
        row = db_conn.execute(
            "SELECT status FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        assert row["status"] == "approved"

    def test_approved_action_included_in_apply_queue(self, db_conn):
        """APPROVAL_REQUIRED + approved is returned by get_pending_apply_tasks."""
        action_id = _insert_approval_required_action(db_conn)
        update_action_status(db_conn, action_id, "approved", actor="operator")
        db_conn.commit()

        tasks = get_pending_apply_tasks(db_conn)
        assert len(tasks) == 1
        assert tasks[0]["action_id"] == action_id
        assert tasks[0]["hh_vacancy_id"] == "hh_test_1"

    def test_approve_triggers_immediate_apply(self, db_conn):
        """handle_approval_callback fires asyncio.create_task(_run_apply_cycle) on approve."""
        from capabilities.career_os.skills.control_plane.handlers import handle_approval_callback

        action_id = _insert_approval_required_action(db_conn)

        # Build a minimal mocked CallbackQuery
        mock_msg = MagicMock()
        mock_msg.text = "Вакансия #123 — тест"
        mock_msg.edit_text = AsyncMock()

        mock_callback = MagicMock()
        mock_callback.data = f"approve:{action_id}"
        mock_callback.from_user.id = 777
        mock_callback.message = mock_msg
        mock_callback.answer = AsyncMock()
        mock_callback.bot = MagicMock()

        created_tasks = []

        def _capture_task(coro):
            created_tasks.append(coro)
            return MagicMock()  # fake Task

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with ExitStack() as stack:
            stack.enter_context(patch(
                "capabilities.career_os.skills.control_plane.handlers.config",
                allowed_telegram_ids=[777],
                hh_apply_enabled=True,
            ))
            stack.enter_context(patch(
                "capabilities.career_os.skills.control_plane.handlers.get_conn",
                return_value=cm,
            ))
            stack.enter_context(patch(
                "capabilities.career_os.skills.control_plane.handlers.emit",
            ))
            stack.enter_context(patch(
                "capabilities.career_os.skills.control_plane.handlers.asyncio.create_task",
                side_effect=_capture_task,
            ))

            asyncio.get_event_loop().run_until_complete(
                handle_approval_callback(mock_callback)
            )

        assert len(created_tasks) == 1, "create_task must be called once on approve"
        mock_callback.answer.assert_called_once()
