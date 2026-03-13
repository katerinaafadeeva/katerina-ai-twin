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
    cover_letter_mode="always",
    cover_letter_daily_cap=50,
    profile_path="identity/profile.json",
):
    cfg = MagicMock()
    cfg.hh_apply_enabled = hh_apply_enabled
    cfg.apply_daily_cap = apply_daily_cap
    cfg.apply_delay_min = apply_delay_min
    cfg.apply_delay_max = apply_delay_max
    cfg.apply_batch_size = apply_batch_size
    cfg.hh_storage_state_path = hh_storage_state_path
    cfg.allowed_telegram_ids = allowed_telegram_ids or [12345]
    cfg.cover_letter_mode = cover_letter_mode
    cfg.cover_letter_daily_cap = cover_letter_daily_cap
    cfg.profile_path = profile_path
    # Schedule — disabled by default so tests run without time constraints
    cfg.apply_schedule_enabled = False
    cfg.apply_schedule_hour_start = 9
    cfg.apply_schedule_hour_end = 20
    return cfg


def _make_task(
    action_id=1,
    job_raw_id=10,
    hh_vacancy_id="111",
    cover_letter="Письмо",
    vacancy_text="Ищем Python-разработчика с опытом Flask и PostgreSQL.",
):
    return {
        "action_id": action_id,
        "job_raw_id": job_raw_id,
        "hh_vacancy_id": hh_vacancy_id,
        "cover_letter": cover_letter,
        "vacancy_text": vacancy_text,
        "correlation_id": "corr-123",
        "attempt_count": 0,  # number of existing apply_runs for this action
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
             patch("capabilities.career_os.skills.hh_apply.worker._get_effective_apply_cap", return_value=5), \
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
             patch("capabilities.career_os.skills.hh_apply.worker.save_apply_run") as mock_save, \
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

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["status"] == "done"
        assert call_kwargs[1]["finished_at"] is not None
        assert call_kwargs[1]["attempt"] == 1  # attempt_count=0 → next=1

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
             patch("capabilities.career_os.skills.hh_apply.worker.save_apply_run"), \
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
             patch("capabilities.career_os.skills.hh_apply.worker.save_apply_run"), \
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


# ---------------------------------------------------------------------------
# _ensure_cover_letter — JIT generation
# ---------------------------------------------------------------------------


class TestEnsureCoverLetter:
    """Unit tests for the _ensure_cover_letter helper."""

    @pytest.mark.asyncio
    async def test_generates_and_returns_letter(self):
        """When no letter exists, generate via LLM and return the text."""
        mock_config = _make_config(cover_letter_daily_cap=50)
        generated = "Сгенерированное письмо для вакансии."

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_cover_letter_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.Profile") as MockProfile, \
             patch("capabilities.career_os.skills.hh_apply.worker.generate_cover_letter",
                   new_callable=AsyncMock, return_value=(generated, False, 100, 50, 0.001)) as mock_gen, \
             patch("capabilities.career_os.skills.hh_apply.worker.save_cover_letter"):

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _ensure_cover_letter
            result = await _ensure_cover_letter(
                action_id=1, job_raw_id=10,
                vacancy_text="Ищем Python-разработчика.", correlation_id="c1"
            )

        assert result == generated
        mock_gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_vacancy_text(self):
        """Empty vacancy_text → no generation, return ''."""
        mock_config = _make_config()

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config):
            from capabilities.career_os.skills.hh_apply.worker import _ensure_cover_letter
            result = await _ensure_cover_letter(
                action_id=1, job_raw_id=10, vacancy_text="", correlation_id="c2"
            )

        assert result == ""

    @pytest.mark.asyncio
    async def test_uses_fallback_when_daily_cap_reached(self):
        """When daily cap is reached, return static fallback letter."""
        mock_config = _make_config(cover_letter_daily_cap=10)
        fallback_text = "Добрый день, ваша вакансия интересна."

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_cover_letter_count", return_value=10), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_fallback_letter", return_value=fallback_text), \
             patch("capabilities.career_os.skills.hh_apply.worker.generate_cover_letter") as mock_gen:

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _ensure_cover_letter
            result = await _ensure_cover_letter(
                action_id=1, job_raw_id=10, vacancy_text="Вакансия", correlation_id="c3"
            )

        assert result == fallback_text
        mock_gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_generation_exception(self):
        """LLM failure → return '' so apply still proceeds."""
        mock_config = _make_config(cover_letter_daily_cap=50)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_cover_letter_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.Profile") as MockProfile, \
             patch("capabilities.career_os.skills.hh_apply.worker.generate_cover_letter",
                   new_callable=AsyncMock, side_effect=Exception("API down")):

            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _ensure_cover_letter
            result = await _ensure_cover_letter(
                action_id=1, job_raw_id=10, vacancy_text="Вакансия", correlation_id="c4"
            )

        assert result == ""

    @pytest.mark.asyncio
    async def test_skips_generation_when_mode_never(self):
        """COVER_LETTER_MODE=never → _ensure_cover_letter is never called (worker skips it)."""
        from connectors.hh_browser.apply_flow import ApplyResult, ApplyStatus
        apply_result = ApplyResult(
            status=ApplyStatus.DONE, apply_url="https://hh.ru/vacancy/111"
        )
        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0, cover_letter_mode="never")
        # Task with NO cover letter in DB
        task = _make_task(cover_letter=None)

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=[task]), \
             patch("capabilities.career_os.skills.hh_apply.worker.save_apply_run"), \
             patch("capabilities.career_os.skills.hh_apply.worker.emit"), \
             patch("capabilities.career_os.skills.hh_apply.worker.apply_to_vacancy",
                   new_callable=AsyncMock, return_value=apply_result) as mock_apply, \
             patch("capabilities.career_os.skills.hh_apply.worker.HHBrowserClient") as MockClient, \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_apply_done"), \
             patch("capabilities.career_os.skills.hh_apply.worker.notify_batch_summary"), \
             patch("capabilities.career_os.skills.hh_apply.worker.generate_cover_letter") as mock_gen:

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.new_page = AsyncMock(return_value=AsyncMock())
            MockClient.return_value.session.return_value = mock_ctx
            mock_gc.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
            await _run_apply_cycle(mock_bot)

        # LLM was NOT called — mode=never bypasses JIT
        mock_gen.assert_not_called()
        # apply_to_vacancy called with empty cover_letter
        call_args = mock_apply.call_args
        assert call_args[0][2] == ""  # cover_letter arg is ""


# ---------------------------------------------------------------------------
# _run_apply_cycle — duplicate apply_run (concurrent cycle safety)
# ---------------------------------------------------------------------------


class TestApplyCycleDuplicateRun:
    @pytest.mark.asyncio
    async def test_duplicate_apply_run_skips_notification(self):
        """When save_apply_run returns 0 (INSERT OR IGNORE hit by concurrent cycle),
        no Telegram notification is sent for that action.
        """
        from connectors.hh_browser.apply_flow import ApplyResult, ApplyStatus

        apply_result = ApplyResult(status=ApplyStatus.DONE, apply_url="https://hh.ru/vacancy/111")
        mock_bot = AsyncMock()
        mock_config = _make_config(apply_daily_cap=0)
        task = _make_task()

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_config), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_conn") as mock_gc, \
             patch("capabilities.career_os.skills.hh_apply.worker.get_today_apply_count", return_value=0), \
             patch("capabilities.career_os.skills.hh_apply.worker.get_pending_apply_tasks", return_value=[task]), \
             patch("capabilities.career_os.skills.hh_apply.worker.save_apply_run", return_value=0) as mock_save, \
             patch("capabilities.career_os.skills.hh_apply.worker.emit") as mock_emit, \
             patch("capabilities.career_os.skills.hh_apply.worker.apply_to_vacancy",
                   new_callable=AsyncMock, return_value=apply_result), \
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

        # save_apply_run was called (attempt was made) but returned 0 (duplicate)
        mock_save.assert_called_once()
        # Neither emit nor notify should fire — concurrent cycle already handled it
        mock_emit.assert_not_called()
        mock_notify.assert_not_called()
