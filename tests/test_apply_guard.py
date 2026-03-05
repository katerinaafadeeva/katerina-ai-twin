"""Tests for ISSUE-2: skip AUTO_APPLY if vacancy was already successfully applied to.

Covers:
- has_successful_apply_for_job: correct True/False based on apply_runs status
- scoring_worker: save_action not called when already applied (mock-based)
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.career_os.skills.apply_policy.store import has_successful_apply_for_job

_W = "capabilities.career_os.skills.match_scoring.worker"


# ---------------------------------------------------------------------------
# has_successful_apply_for_job — store-level tests
# ---------------------------------------------------------------------------


class TestHasSuccessfulApplyForJob:
    def _setup(self, conn, job_raw_id: int, status: str) -> None:
        conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (?, ?, 'hh', ?)",
            (job_raw_id, "vacancy", f"hh_{job_raw_id}"),
        )
        action_id = job_raw_id * 10
        conn.execute(
            "INSERT INTO actions (id, job_raw_id, action_type, status) VALUES (?, ?, 'AUTO_APPLY', 'pending')",
            (action_id, job_raw_id),
        )
        conn.execute(
            "INSERT INTO apply_runs (action_id, attempt, status, finished_at) VALUES (?, 1, ?, datetime('now'))",
            (action_id, status),
        )
        conn.commit()

    def test_returns_true_when_done(self, db_conn):
        self._setup(db_conn, 1, "done")
        assert has_successful_apply_for_job(db_conn, 1) is True

    def test_returns_true_when_done_without_letter(self, db_conn):
        self._setup(db_conn, 2, "done_without_letter")
        assert has_successful_apply_for_job(db_conn, 2) is True

    def test_returns_false_when_no_apply_runs(self, db_conn):
        db_conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (1, 'text', 'hh', 'hh_1')"
        )
        db_conn.commit()
        assert has_successful_apply_for_job(db_conn, 1) is False

    def test_returns_false_when_only_failed(self, db_conn):
        self._setup(db_conn, 3, "failed")
        assert has_successful_apply_for_job(db_conn, 3) is False

    def test_returns_false_when_only_already_applied(self, db_conn):
        self._setup(db_conn, 4, "already_applied")
        assert has_successful_apply_for_job(db_conn, 4) is False

    def test_returns_false_for_different_job(self, db_conn):
        self._setup(db_conn, 5, "done")
        db_conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (6, 'other', 'hh', 'hh_6')"
        )
        db_conn.commit()
        assert has_successful_apply_for_job(db_conn, 6) is False


# ---------------------------------------------------------------------------
# scoring_worker ISSUE-2 guard — mock-based test using ExitStack
# ---------------------------------------------------------------------------


def _make_cfg():
    cfg = MagicMock()
    cfg.hh_scoring_daily_cap = 0
    cfg.tg_scoring_daily_cap = 0
    cfg.cover_letter_daily_cap = 0
    cfg.allowed_telegram_ids = [12345]
    cfg.profile_path = "identity/profile.json"
    cfg.resume_path = "identity/resume.md"
    cfg.scoring_worker_interval = 999
    return cfg


async def _run_worker(mock_bot, patches_dict):
    """Run scoring_worker one iteration using ExitStack for all patches."""
    with contextlib.ExitStack() as stack:
        for target, val in patches_dict.items():
            if isinstance(val, dict):
                stack.enter_context(patch(target, **val))
            else:
                stack.enter_context(patch(target, val))

        stack.enter_context(
            patch(_W + ".asyncio.sleep",
                  new_callable=AsyncMock, side_effect=asyncio.CancelledError)
        )
        from capabilities.career_os.skills.match_scoring.worker import scoring_worker
        try:
            await scoring_worker(mock_bot)
        except asyncio.CancelledError:
            pass


class TestAutoApplyGuard:
    @pytest.mark.asyncio
    async def test_save_action_not_called_when_already_applied(self):
        """save_action must NOT be called when already applied (ISSUE-2 guard fires)."""
        mock_bot = AsyncMock()
        save_action_mock = MagicMock(return_value=1)

        async def mock_score(vacancy_text, vacancy_id, profile, correlation_id):
            r = MagicMock()
            r.score = 7
            r.reasons = []
            r.explanation = "good"
            return r

        mock_gc = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_profile_cls = MagicMock()
        mock_profile_cls.from_file.return_value = MagicMock()

        vacancy = {"id": 42, "raw_text": "Python dev", "source": "hh", "hh_vacancy_id": "hh42"}

        patches = {
            _W + ".config": _make_cfg(),
            _W + ".get_conn": mock_gc,
            _W + ".Profile": mock_profile_cls,
            _W + ".get_unscored_vacancies": {"return_value": [vacancy]},
            _W + ".get_today_scored_count_by_source": {"return_value": 0},
            _W + ".score_vacancy_llm": {"new_callable": AsyncMock, "side_effect": mock_score},
            _W + ".save_score": {"return_value": None},
            _W + ".get_policy": {
                "return_value": {"threshold_low": 5, "threshold_high": 8, "daily_limit": 100}
            },
            _W + ".get_today_auto_count": {"return_value": 0},
            _W + ".has_successful_apply_for_job": {"return_value": True},
            _W + ".save_action": {"side_effect": save_action_mock},
            _W + ".emit": {"return_value": None},
            _W + ".get_today_hold_count": {"return_value": 0},
            _W + ".was_hold_notification_sent_today": {"return_value": True},
            _W + ".was_scoring_cap_notification_sent_today": {"return_value": True},
            _W + ".was_tg_scoring_cap_notification_sent_today": {"return_value": True},
            _W + ".was_cover_letter_cap_notification_sent_today": {"return_value": True},
            _W + ".get_today_cover_letter_count": {"return_value": 0},
            _W + ".get_resume_text": {"return_value": "resume"},
        }

        await _run_worker(mock_bot, patches)
        save_action_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_action_called_when_not_yet_applied(self):
        """save_action MUST be called when vacancy has never been applied to."""
        mock_bot = AsyncMock()
        save_action_mock = MagicMock(return_value=1)

        async def mock_score(vacancy_text, vacancy_id, profile, correlation_id):
            r = MagicMock()
            r.score = 7
            r.reasons = []
            r.explanation = "good"
            return r

        mock_gc = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_profile_cls = MagicMock()
        mock_profile_cls.from_file.return_value = MagicMock()

        vacancy = {"id": 43, "raw_text": "Python dev", "source": "hh", "hh_vacancy_id": "hh43"}

        patches = {
            _W + ".config": _make_cfg(),
            _W + ".get_conn": mock_gc,
            _W + ".Profile": mock_profile_cls,
            _W + ".get_unscored_vacancies": {"return_value": [vacancy]},
            _W + ".get_today_scored_count_by_source": {"return_value": 0},
            _W + ".score_vacancy_llm": {"new_callable": AsyncMock, "side_effect": mock_score},
            _W + ".save_score": {"return_value": None},
            _W + ".get_policy": {
                "return_value": {"threshold_low": 5, "threshold_high": 8, "daily_limit": 100}
            },
            _W + ".get_today_auto_count": {"return_value": 0},
            _W + ".has_successful_apply_for_job": {"return_value": False},
            _W + ".save_action": {"side_effect": save_action_mock},
            _W + ".emit": {"return_value": None},
            _W + ".get_today_hold_count": {"return_value": 0},
            _W + ".was_hold_notification_sent_today": {"return_value": True},
            _W + ".was_scoring_cap_notification_sent_today": {"return_value": True},
            _W + ".was_tg_scoring_cap_notification_sent_today": {"return_value": True},
            _W + ".was_cover_letter_cap_notification_sent_today": {"return_value": True},
            _W + ".get_today_cover_letter_count": {"return_value": 0},
            _W + ".get_resume_text": {"return_value": "resume"},
            _W + ".generate_cover_letter": {
                "new_callable": AsyncMock,
                "return_value": ("letter text", False, 10, 5, 0.001),
            },
            _W + ".save_cover_letter": {"return_value": None},
        }

        await _run_worker(mock_bot, patches)
        save_action_mock.assert_called_once()
