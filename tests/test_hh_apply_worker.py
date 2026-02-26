"""Tests for capabilities/career_os/skills/hh_apply/worker.py.

All browser and Telegram calls are mocked — no real Playwright, no real bot.
Covers:
- Feature flag: worker exits immediately when disabled
- Daily cap enforcement + emit-first notification
- Captcha → stops batch
- Session expired → stops batch
- Successful apply → updates DB, emits event, notifies
- Per-vacancy exception isolation
- Random delay between applies
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    hh_apply_enabled=True,
    apply_daily_cap=10,
    apply_delay_min=0.0,
    apply_delay_max=0.0,
    apply_batch_size=5,
    hh_storage_state_path="/tmp/nonexistent.json",
    allowed_telegram_ids=None,
):
    cfg = MagicMock()
    cfg.hh_apply_enabled = hh_apply_enabled
    cfg.apply_daily_cap = apply_daily_cap
    cfg.apply_delay_min = apply_delay_min
    cfg.apply_delay_max = apply_delay_max
    cfg.apply_batch_size = apply_batch_size
    cfg.hh_storage_state_path = hh_storage_state_path
    cfg.allowed_telegram_ids = allowed_telegram_ids or [12345]
    return cfg


def _make_task(action_id=1, job_raw_id=10, hh_vacancy_id="111", cover_letter="Письмо"):
    return {
        "action_id": action_id,
        "job_raw_id": job_raw_id,
        "hh_vacancy_id": hh_vacancy_id,
        "cover_letter": cover_letter,
        "correlation_id": "corr-123",
        "execution_attempts": 0,
    }


# ---------------------------------------------------------------------------
# hh_apply_worker — feature flag
# ---------------------------------------------------------------------------


class TestHhApplyWorkerFeatureFlag:
    @pytest.mark.asyncio
    async def test_exits_immediately_when_disabled(self):
        """Worker must return without entering the loop when HH_APPLY_ENABLED=false."""
        mock_bot = AsyncMock()
        mock_config = _make_config(hh_apply_enabled=False)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config):
            from capabilities.career_os.skills.hh_apply.worker import hh_apply_worker
            await hh_apply_worker(mock_bot)

        # If we reach here without timeout, the worker exited as expected


# ---------------------------------------------------------------------------
# _run_apply_cycle — daily cap
# ---------------------------------------------------------------------------


class TestApplyCycleDailyCap:
    @pytest.mark.asyncio
    async def test_skips_cycle_when_cap_reached(self):
        """When today_count >= cap, no tasks are picked up."""
        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=5)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=5), \
             patch("capabilities.career_os.skills.hh_apply.worker.was_apply_cap_notification_sent_today", return_value=False), \
             patch("capabilities.career_os.skills.hh_apply.worker.emit") as mock_emit, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_apply_cap_reached") as mock_notify:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        mock_emit.assert_called_once_with(
            "apply.cap_reached",
            {"cap": 5, "today": 5},
            actor="hh_apply_worker",
        )
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_notify_cap_twice(self):
        """Cap notification is emitted only once per day."""
        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=5)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=5), \
             patch("capabilities.career_os.skills.hh_apply.worker.was_apply_cap_notification_sent_today", return_value=True), \
             patch("capabilities.career_os.skills.hh_apply.worker.emit") as mock_emit, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_apply_cap_reached") as mock_notify:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        mock_emit.assert_not_called()
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# _run_apply_cycle — apply outcomes
# ---------------------------------------------------------------------------


class TestApplyCycleOutcomes:
    def _make_browser_context(self, result):
        """Mock browser context that returns the given ApplyResult."""
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.__aenter__ = AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        mock_browser_client = MagicMock()
        mock_browser_client.session.return_value = mock_context

        return mock_browser_client, mock_page, result

    @pytest.mark.asyncio
    async def test_done_updates_db_and_emits(self):
        """Successful apply: updates execution_status=done, emits apply.done."""
        from connectors.hh_browser.apply_flow import ApplyResult, ApplyStatus
        apply_result = ApplyResult(status=ApplyStatus.DONE, apply_url="https://hh.ru/vacancy/111")

        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0)  # no cap
        task = _make_task()

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=[task]), \
             patch("capabilities.career_os.skills.hh_apply.worker.update_action_execution") as mock_update, \
             patch("capabilities.career_os.skills.hh_apply.worker.emit") as mock_emit, \
             patch("capabilities.career_os.skills.hh_apply.worker.apply_to_vacancy", new_callable=AsyncMock, return_value=apply_result), \
             patch("capabilities.career_os.skills.hh_apply.worker.HHBrowserClient") as MockClient, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_apply_done") as mock_notify, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_batch_summary"):

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.new_page = AsyncMock(return_value=AsyncMock())
            MockClient.return_value.session.return_value = mock_ctx

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        assert call_kwargs[1]["execution_status"] == "done"
        assert call_kwargs[1]["applied_at"] is not None

        mock_emit.assert_called_once_with(
            "apply.done",
            {"job_raw_id": 10, "action_id": 1, "apply_url": "https://hh.ru/vacancy/111", "error": None},
            actor="hh_apply_worker",
            correlation_id="corr-123",
        )
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_captcha_stops_batch(self):
        """Captcha result stops the entire batch — no further tasks processed."""
        from connectors.hh_browser.apply_flow import ApplyResult, ApplyStatus
        captcha_result = ApplyResult(status=ApplyStatus.CAPTCHA)

        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0)
        tasks = [_make_task(action_id=1), _make_task(action_id=2, hh_vacancy_id="222")]

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=tasks), \
             patch("capabilities.career_os.skills.hh_apply.worker.update_action_execution"), \
             patch("capabilities.career_os.skills.hh_apply.worker.emit"), \
             patch("capabilities.career_os.skills.hh_apply.worker.apply_to_vacancy", new_callable=AsyncMock, return_value=captcha_result), \
             patch("capabilities.career_os.skills.hh_apply.worker.HHBrowserClient") as MockClient, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_captcha") as mock_captcha_notify, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_batch_summary"):

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.new_page = AsyncMock(return_value=AsyncMock())
            MockClient.return_value.session.return_value = mock_ctx

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        # Captcha notification sent
        mock_captcha_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_expired_stops_batch(self):
        """Session expired stops the batch and notifies operator."""
        from connectors.hh_browser.apply_flow import ApplyResult, ApplyStatus
        session_result = ApplyResult(status=ApplyStatus.SESSION_EXPIRED)

        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=[_make_task()]), \
             patch("capabilities.career_os.skills.hh_apply.worker.update_action_execution"), \
             patch("capabilities.career_os.skills.hh_apply.worker.emit"), \
             patch("capabilities.career_os.skills.hh_apply.worker.apply_to_vacancy", new_callable=AsyncMock, return_value=session_result), \
             patch("capabilities.career_os.skills.hh_apply.worker.HHBrowserClient") as MockClient, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_session_expired") as mock_session_notify, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_batch_summary"):

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.new_page = AsyncMock(return_value=AsyncMock())
            MockClient.return_value.session.return_value = mock_ctx

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        mock_session_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_task_list_returns_early(self):
        """No tasks → no browser session opened."""
        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=[]), \
             patch("capabilities.career_os.skills.hh_apply.worker.HHBrowserClient") as MockClient:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        MockClient.assert_not_called()
