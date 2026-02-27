"""Regression tests for PR fixes:

Task A — scorer_version uses PROMPT_VERSION (not hardcoded "v1"):
  test_scorer_version_matches_prompt_version
  test_save_score_called_with_prompt_version

Task B — /stats shows decisions_today, not auto_count:
  test_cmd_stats_uses_decisions_today_not_auto_count

Task C1 — cmd_resume_apply is a coroutine function (no RuntimeWarning):
  test_cmd_resume_apply_is_coroutinefunction
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Task A: scorer_version in worker matches PROMPT_VERSION
# ---------------------------------------------------------------------------


class TestScorerVersion:
    def test_scorer_version_matches_prompt_version(self):
        """PROMPT_VERSION imported in worker must equal the scoring prompt constant."""
        from core.llm.prompts.scoring_v1 import PROMPT_VERSION as prompt_const
        import capabilities.career_os.skills.match_scoring.worker as w

        assert w.PROMPT_VERSION == prompt_const
        assert w.PROMPT_VERSION == "scoring_v2"

    @pytest.mark.asyncio
    async def test_save_score_called_with_scorer_version_v2(self, sample_profile):
        """scoring_worker passes scorer_version=PROMPT_VERSION to save_score."""
        import capabilities.career_os.skills.match_scoring.worker as w
        from core.llm.schemas import ScoreReason, ScoringOutput

        llm_result = ScoringOutput(
            score=7,
            reasons=[ScoreReason(criterion="role_match", matched=True, note="ok")],
            explanation="Хорошее совпадение по роли и опыту.",
        )

        mock_config = MagicMock()
        mock_config.scoring_worker_interval = 999999
        mock_config.profile_path = "identity/profile.example.json"
        mock_config.hh_scoring_daily_cap = 0
        mock_config.cover_letter_daily_cap = 0
        mock_config.allowed_telegram_ids = []
        mock_config.apply_daily_cap = 10
        mock_config.resume_path = "/nonexistent/resume.md"

        save_score_calls = []

        def capturing_save_score(conn, job_raw_id, result, **kwargs):
            save_score_calls.append(kwargs)
            return 1

        vacancy = {
            "id": 1,
            "raw_text": "Product Manager vacancy",
            "source": "hh",
            "hh_vacancy_id": "111",
        }

        # Patch everything so the worker runs exactly one vacancy and then sleeps forever
        with patch.object(w, "config", mock_config), \
             patch.object(w, "get_unscored_vacancies", return_value=[vacancy]), \
             patch.object(w, "score_vacancy_llm", AsyncMock(return_value=llm_result)), \
             patch.object(w, "save_score", side_effect=capturing_save_score), \
             patch.object(w, "get_conn") as mock_gc, \
             patch.object(w, "get_policy", return_value={"threshold_low": 5, "threshold_high": 7, "daily_limit": 40}), \
             patch.object(w, "get_today_auto_count", return_value=0), \
             patch.object(w, "save_action", return_value=1), \
             patch.object(w, "emit"), \
             patch.object(w, "get_today_hold_count", return_value=0), \
             patch.object(w, "was_hold_notification_sent_today", return_value=True), \
             patch.object(w, "get_today_cover_letter_count", return_value=0), \
             patch.object(w, "was_cover_letter_cap_notification_sent_today", return_value=True), \
             patch.object(w, "was_scoring_cap_notification_sent_today", return_value=True), \
             patch("asyncio.sleep", side_effect=asyncio.CancelledError):

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            mock_bot = AsyncMock()
            try:
                await w.scoring_worker(mock_bot)
            except asyncio.CancelledError:
                pass

        assert save_score_calls, "save_score must have been called"
        call_kwargs = save_score_calls[0]
        assert call_kwargs.get("scorer_version") == "scoring_v2", (
            f"Expected scorer_version='scoring_v2', got {call_kwargs.get('scorer_version')!r}"
        )

    @pytest.mark.asyncio
    async def test_get_unscored_vacancies_called_with_scorer_version_v2(self, sample_profile):
        """scoring_worker queries unscored with scorer_version=PROMPT_VERSION."""
        import capabilities.career_os.skills.match_scoring.worker as w

        get_unscored_calls = []

        def capturing_get_unscored(conn, scorer_version="v1"):
            get_unscored_calls.append(scorer_version)
            return []  # No vacancies → loop ends quickly

        mock_config = MagicMock()
        mock_config.scoring_worker_interval = 999999
        mock_config.profile_path = "identity/profile.example.json"
        mock_config.hh_scoring_daily_cap = 0
        mock_config.cover_letter_daily_cap = 0
        mock_config.allowed_telegram_ids = []
        mock_config.resume_path = "/nonexistent/resume.md"

        with patch.object(w, "config", mock_config), \
             patch.object(w, "get_unscored_vacancies", side_effect=capturing_get_unscored), \
             patch.object(w, "get_conn") as mock_gc, \
             patch.object(w, "get_today_hold_count", return_value=0), \
             patch.object(w, "was_hold_notification_sent_today", return_value=True), \
             patch.object(w, "get_today_cover_letter_count", return_value=0), \
             patch.object(w, "was_cover_letter_cap_notification_sent_today", return_value=True), \
             patch.object(w, "was_scoring_cap_notification_sent_today", return_value=True), \
             patch("asyncio.sleep", side_effect=asyncio.CancelledError):

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            mock_bot = AsyncMock()
            try:
                await w.scoring_worker(mock_bot)
            except asyncio.CancelledError:
                pass

        assert get_unscored_calls, "get_unscored_vacancies must have been called"
        assert get_unscored_calls[0] == "scoring_v2", (
            f"Expected scorer_version='scoring_v2', got {get_unscored_calls[0]!r}"
        )


# ---------------------------------------------------------------------------
# Task B: cmd_stats uses decisions_today, not auto_count
# ---------------------------------------------------------------------------


class TestCmdStatsUsesDecisionsToday:
    @pytest.mark.asyncio
    async def test_cmd_stats_uses_decisions_today_not_auto_count(self):
        """/stats 'Лимит решений' must use decisions_today, not auto_count."""
        from capabilities.career_os.skills.control_plane.handlers import cmd_stats

        # Summary where auto_count (1) ≠ decisions_today (7)
        fake_summary = {
            "total_ingested": 10,
            "total_scored": 8,
            "by_action_type": {
                "IGNORE": 2, "AUTO_QUEUE": 1, "AUTO_APPLY": 1,
                "HOLD": 1, "APPROVAL_REQUIRED": 2,
            },
            "by_status": {
                "pending": 5, "approved": 1, "rejected": 1, "snoozed": 0,
            },
            "decisions_today": 7,   # should appear
            "auto_count": 1,        # must NOT appear in this line
            "daily_limit": 40,
            "remaining": 39,
            "applies_done": 2,
            "apply_daily_cap": 5,
        }

        captured_text = []
        mock_message = AsyncMock()
        mock_message.from_user = MagicMock()
        mock_message.from_user.id = 12345

        async def capture_answer(text, **kwargs):
            captured_text.append(text)

        mock_message.answer = capture_answer

        with patch("capabilities.career_os.skills.control_plane.handlers.is_authorized", return_value=True), \
             patch("capabilities.career_os.skills.control_plane.handlers.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.control_plane.handlers.get_today_summary", return_value=fake_summary), \
             patch("capabilities.career_os.skills.control_plane.handlers.get_pending_approvals", return_value=[]), \
             patch("capabilities.career_os.skills.control_plane.handlers.config") as mock_cfg:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            mock_cfg.apply_daily_cap = 5

            await cmd_stats(mock_message)

        assert captured_text, "cmd_stats must call message.answer()"
        text = captured_text[0]

        # The limit line must use decisions_today=7
        assert "7/40" in text, f"Expected '7/40' in stats text, got:\n{text}"
        # Make sure we didn't accidentally use auto_count=1 in this specific format
        assert "1/40" not in text, f"'1/40' (auto_count) must not appear in stats text, got:\n{text}"

    @pytest.mark.asyncio
    async def test_cmd_stats_remaining_is_daily_limit_minus_decisions_today(self):
        """/stats remaining capacity = daily_limit - decisions_today."""
        from capabilities.career_os.skills.control_plane.handlers import cmd_stats

        fake_summary = {
            "total_ingested": 5,
            "total_scored": 5,
            "by_action_type": {
                "IGNORE": 0, "AUTO_QUEUE": 0, "AUTO_APPLY": 0,
                "HOLD": 0, "APPROVAL_REQUIRED": 5,
            },
            "by_status": {"pending": 5, "approved": 0, "rejected": 0, "snoozed": 0},
            "decisions_today": 5,
            "auto_count": 0,
            "daily_limit": 40,
            "remaining": 40,   # intentionally stale — handler must recompute
            "applies_done": 0,
            "apply_daily_cap": 5,
        }

        captured_text = []
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock(side_effect=lambda t, **kw: captured_text.append(t))

        with patch("capabilities.career_os.skills.control_plane.handlers.is_authorized", return_value=True), \
             patch("capabilities.career_os.skills.control_plane.handlers.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.control_plane.handlers.get_today_summary", return_value=fake_summary), \
             patch("capabilities.career_os.skills.control_plane.handlers.get_pending_approvals", return_value=[]), \
             patch("capabilities.career_os.skills.control_plane.handlers.config") as mock_cfg:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            mock_cfg.apply_daily_cap = 5

            await cmd_stats(mock_message)

        assert captured_text
        text = captured_text[0]
        # decisions_today=5, daily_limit=40 → remaining=35
        assert "5/40" in text
        assert "осталось 35" in text


# ---------------------------------------------------------------------------
# Task C1: cmd_resume_apply is a coroutine function
# ---------------------------------------------------------------------------


class TestCmdResumeApplyIsCoroutine:
    def test_cmd_resume_apply_is_coroutinefunction(self):
        """cmd_resume_apply must be a coroutine function (async def), not a sync lambda."""
        from connectors.telegram_bot import cmd_resume_apply
        assert asyncio.iscoroutinefunction(cmd_resume_apply), (
            "cmd_resume_apply must be declared as 'async def'. "
            "A sync wrapper (lambda) causes RuntimeWarning: coroutine was never awaited."
        )

    @pytest.mark.asyncio
    async def test_cmd_resume_apply_can_be_awaited(self):
        """cmd_resume_apply can be awaited without RuntimeWarning."""
        from connectors.telegram_bot import cmd_resume_apply

        mock_message = AsyncMock()
        mock_message.from_user = MagicMock()
        mock_message.from_user.id = 12345
        mock_bot = AsyncMock()

        with patch("connectors.telegram_bot.is_authorized", return_value=False):
            # is_authorized=False → returns early, no bot/DB calls needed
            await cmd_resume_apply(mock_message, mock_bot)
        # No exception = can be awaited


# ---------------------------------------------------------------------------
# Task D: /start sends ALLOWED_TELEGRAM_IDS warning when list is empty
# ---------------------------------------------------------------------------


class TestCmdStartWarning:
    @pytest.mark.asyncio
    async def test_warns_when_allowed_telegram_ids_empty(self):
        """/start must send an extra warning when ALLOWED_TELEGRAM_IDS is empty."""
        from connectors.telegram_bot import cmd_start

        answers = []
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock(side_effect=lambda t, **kw: answers.append(t))

        with patch("connectors.telegram_bot.is_authorized", return_value=True), \
             patch("connectors.telegram_bot.config") as mock_cfg:
            mock_cfg.allowed_telegram_ids = []
            await cmd_start(mock_message)

        assert len(answers) >= 2, "Must send greeting AND warning when IDs empty"
        combined = " ".join(answers)
        assert "ALLOWED_TELEGRAM_IDS" in combined, (
            "Warning must mention ALLOWED_TELEGRAM_IDS"
        )

    @pytest.mark.asyncio
    async def test_no_warning_when_allowed_telegram_ids_set(self):
        """/start must NOT send a warning when ALLOWED_TELEGRAM_IDS is configured."""
        from connectors.telegram_bot import cmd_start

        answers = []
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock(side_effect=lambda t, **kw: answers.append(t))

        with patch("connectors.telegram_bot.is_authorized", return_value=True), \
             patch("connectors.telegram_bot.config") as mock_cfg:
            mock_cfg.allowed_telegram_ids = [12345]
            await cmd_start(mock_message)

        assert len(answers) == 1, "Should send exactly one greeting, no warning"
        assert "ALLOWED_TELEGRAM_IDS" not in answers[0]
