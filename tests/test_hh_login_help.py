"""Tests for /hh_login_help command and hh_apply worker startup check.

Covers:
- cmd_hh_login_help: shows "❌ Файл сессии отсутствует" when file missing
- cmd_hh_login_help: shows "✅ Файл сессии найден" when file exists
- cmd_hh_login_help: shows apply_enabled status
- hh_apply_worker: sends warning when storage state missing at startup
- hh_apply_worker: does NOT send warning when storage state exists
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCmdHhLoginHelp:
    @pytest.mark.asyncio
    async def test_shows_missing_when_no_file(self, monkeypatch):
        """When storage state file absent: message contains ❌."""
        from connectors.telegram_bot import cmd_hh_login_help

        mock_message = AsyncMock()
        mock_message.from_user = MagicMock(id=12345)

        mock_cfg = MagicMock()
        mock_cfg.hh_storage_state_path = "/nonexistent/path.json"
        mock_cfg.hh_apply_enabled = False
        mock_cfg.allowed_telegram_ids = [12345]

        with patch("connectors.telegram_bot.config", mock_cfg), \
             patch("connectors.telegram_bot.is_authorized", return_value=True), \
             patch("os.path.exists", return_value=False):
            await cmd_hh_login_help(mock_message)

        mock_message.answer.assert_called_once()
        sent_text = mock_message.answer.call_args[0][0]
        assert "❌" in sent_text

    @pytest.mark.asyncio
    async def test_shows_found_when_file_exists(self, monkeypatch):
        """When storage state file exists: message contains ✅."""
        from connectors.telegram_bot import cmd_hh_login_help

        mock_message = AsyncMock()
        mock_message.from_user = MagicMock(id=12345)

        mock_cfg = MagicMock()
        mock_cfg.hh_storage_state_path = "/tmp/hh_storage_state.json"
        mock_cfg.hh_apply_enabled = True
        mock_cfg.allowed_telegram_ids = [12345]

        with patch("connectors.telegram_bot.config", mock_cfg), \
             patch("connectors.telegram_bot.is_authorized", return_value=True), \
             patch("os.path.exists", return_value=True):
            await cmd_hh_login_help(mock_message)

        mock_message.answer.assert_called_once()
        sent_text = mock_message.answer.call_args[0][0]
        assert "✅" in sent_text

    @pytest.mark.asyncio
    async def test_shows_apply_enabled_status(self, monkeypatch):
        """Message includes apply_enabled information."""
        from connectors.telegram_bot import cmd_hh_login_help

        mock_message = AsyncMock()
        mock_message.from_user = MagicMock(id=12345)

        mock_cfg = MagicMock()
        mock_cfg.hh_storage_state_path = "/tmp/path.json"
        mock_cfg.hh_apply_enabled = True
        mock_cfg.allowed_telegram_ids = [12345]

        with patch("connectors.telegram_bot.config", mock_cfg), \
             patch("connectors.telegram_bot.is_authorized", return_value=True), \
             patch("os.path.exists", return_value=True):
            await cmd_hh_login_help(mock_message)

        sent_text = mock_message.answer.call_args[0][0]
        # Should mention apply is enabled
        assert "HH_APPLY_ENABLED" in sent_text

    @pytest.mark.asyncio
    async def test_unauthorized_returns_without_response(self):
        """Unauthorized user gets no response."""
        from connectors.telegram_bot import cmd_hh_login_help

        mock_message = AsyncMock()

        with patch("connectors.telegram_bot.is_authorized", return_value=False):
            await cmd_hh_login_help(mock_message)

        mock_message.answer.assert_not_called()


class TestApplyWorkerStorageStateCheck:
    @pytest.mark.asyncio
    async def test_warns_when_storage_state_missing(self):
        """Worker sends Telegram warning when storage state file not found."""
        mock_bot = AsyncMock()
        mock_cfg = MagicMock()
        mock_cfg.hh_apply_enabled = True
        mock_cfg.hh_storage_state_path = "/nonexistent/state.json"
        mock_cfg.allowed_telegram_ids = [12345]
        mock_cfg.apply_daily_cap = 10
        mock_cfg.apply_delay_min = 0.0
        mock_cfg.apply_delay_max = 0.0
        mock_cfg.apply_batch_size = 5

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_cfg), \
             patch("os.path.exists", return_value=False), \
             patch("capabilities.career_os.skills.hh_apply.worker._run_apply_cycle") as mock_cycle, \
             patch("asyncio.sleep", side_effect=Exception("stop loop")):
            from capabilities.career_os.skills.hh_apply.worker import hh_apply_worker
            try:
                await hh_apply_worker(mock_bot)
            except Exception:
                pass

        # Bot should have sent a warning about missing session
        mock_bot.send_message.assert_called_once()
        args = mock_bot.send_message.call_args
        assert "⚠️" in args[0][1] or "⚠️" in str(args)

    @pytest.mark.asyncio
    async def test_no_warning_when_storage_state_exists(self):
        """Worker does NOT send warning when storage state file exists."""
        mock_bot = AsyncMock()
        mock_cfg = MagicMock()
        mock_cfg.hh_apply_enabled = True
        mock_cfg.hh_storage_state_path = "/tmp/exists.json"
        mock_cfg.allowed_telegram_ids = [12345]
        mock_cfg.apply_daily_cap = 10
        mock_cfg.apply_delay_min = 0.0
        mock_cfg.apply_delay_max = 0.0
        mock_cfg.apply_batch_size = 5

        with patch("capabilities.career_os.skills.hh_apply.worker.config", mock_cfg), \
             patch("os.path.exists", return_value=True), \
             patch("capabilities.career_os.skills.hh_apply.worker._run_apply_cycle"), \
             patch("asyncio.sleep", side_effect=Exception("stop loop")):
            from capabilities.career_os.skills.hh_apply.worker import hh_apply_worker
            try:
                await hh_apply_worker(mock_bot)
            except Exception:
                pass

        mock_bot.send_message.assert_not_called()
