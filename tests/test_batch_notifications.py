"""Tests for batch notification with vacancy names."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from capabilities.career_os.skills.hh_apply.notifier import notify_batch_summary


@pytest.mark.asyncio
async def test_batch_notification_includes_vacancy_names():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    results = [
        {"title": "Product Manager — ACME", "url": "https://hh.ru/vacancy/111", "status": "done", "error": None},
    ]
    await notify_batch_summary(bot, 123, done=1, skipped=0, failed=0, manual=0, results=results)

    call_text = bot.send_message.call_args[0][1]
    assert "Product Manager — ACME" in call_text
    assert "hh.ru/vacancy/111" in call_text


@pytest.mark.asyncio
async def test_batch_notification_shows_skipped_with_names():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    results = [
        {"title": "PM — Company B", "url": "https://hh.ru/vacancy/222", "status": "already_applied", "error": None},
    ]
    await notify_batch_summary(bot, 123, done=0, skipped=1, failed=0, manual=0, results=results)

    call_text = bot.send_message.call_args[0][1]
    assert "PM — Company B" in call_text
    assert "уже откликались" in call_text


@pytest.mark.asyncio
async def test_batch_notification_shows_errors_with_names():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    results = [
        {"title": "Analyst — Corp", "url": "https://hh.ru/vacancy/333", "status": "failed", "error": "timeout"},
    ]
    await notify_batch_summary(bot, 123, done=0, skipped=0, failed=1, manual=0, results=results)

    call_text = bot.send_message.call_args[0][1]
    assert "Analyst — Corp" in call_text
    assert "ошибок" in call_text


@pytest.mark.asyncio
async def test_batch_notification_empty_returns_without_send():
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await notify_batch_summary(bot, 123, done=0, skipped=0, failed=0, manual=0)
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_batch_notification_legacy_no_results():
    """Test backward compatibility: no results param → counts only."""
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await notify_batch_summary(bot, 123, done=2, skipped=1, failed=0, manual=0)
    call_text = bot.send_message.call_args[0][1]
    assert "✅2 отправлено" in call_text
    assert "уже откликались" in call_text
