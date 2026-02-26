"""Telegram notification helpers for hh_apply outcomes.

All functions accept a Bot instance and a chat_id.
Each function corresponds to one apply outcome.
No LLM calls — pure message formatting.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def notify_apply_done(
    bot,
    chat_id: int,
    job_raw_id: int,
    apply_url: str,
) -> None:
    """Notify operator that an application was submitted successfully."""
    try:
        await bot.send_message(
            chat_id,
            f"✅ Отклик отправлен: вакансия #{job_raw_id}\n{apply_url}",
        )
    except Exception:
        logger.exception("Failed to send apply_done notification for job %d", job_raw_id)


async def notify_manual_required(
    bot,
    chat_id: int,
    job_raw_id: int,
    apply_url: str,
) -> None:
    """Notify operator that manual action is required (apply button not found)."""
    try:
        await bot.send_message(
            chat_id,
            f"⚠️ Требуется ручное действие: вакансия #{job_raw_id}\n"
            f"Кнопка отклика не найдена. Откликнитесь вручную:\n{apply_url}",
        )
    except Exception:
        logger.exception("Failed to send manual_required notification for job %d", job_raw_id)


async def notify_captcha(
    bot,
    chat_id: int,
) -> None:
    """Notify operator that a captcha was detected — batch stopped."""
    try:
        await bot.send_message(
            chat_id,
            "🤖 Обнаружена капча на HH.ru — авто-отклики приостановлены.\n"
            "Зайдите на hh.ru вручную и решите капчу, затем бот продолжит работу.",
        )
    except Exception:
        logger.exception("Failed to send captcha notification")


async def notify_session_expired(
    bot,
    chat_id: int,
) -> None:
    """Notify operator that the HH.ru session has expired."""
    try:
        await bot.send_message(
            chat_id,
            "🔑 Сессия HH.ru истекла — авто-отклики остановлены.\n"
            "Выполните повторную авторизацию:\n"
            "  python -m connectors.hh_browser.bootstrap\n"
            "Затем перезапустите бота.",
        )
    except Exception:
        logger.exception("Failed to send session_expired notification")


async def notify_batch_summary(
    bot,
    chat_id: int,
    done: int,
    skipped: int,
    failed: int,
    manual: int,
) -> None:
    """Send a summary notification after a batch cycle completes."""
    if done == 0 and skipped == 0 and failed == 0 and manual == 0:
        return  # Nothing happened — no message
    try:
        lines = [f"📋 Batch отклики: ✅{done} отправлено"]
        if skipped:
            lines.append(f"  ⏩ {skipped} уже откликались")
        if manual:
            lines.append(f"  ⚠️ {manual} требуют ручного действия")
        if failed:
            lines.append(f"  ❌ {failed} ошибок (повтор до 3 попыток)")
        await bot.send_message(chat_id, "\n".join(lines))
    except Exception:
        logger.exception("Failed to send batch_summary notification")


async def notify_apply_cap_reached(
    bot,
    chat_id: int,
    cap: int,
) -> None:
    """Notify operator that the daily apply cap has been reached."""
    try:
        await bot.send_message(
            chat_id,
            f"🔒 Лимит откликов достигнут: {cap}/день.\n"
            f"Дальнейшие отклики будут отправлены завтра.",
        )
    except Exception:
        logger.exception("Failed to send apply_cap_reached notification")


async def notify_resume_apply(
    bot,
    chat_id: int,
    pending_count: int,
) -> None:
    """Acknowledge /resume_apply command."""
    try:
        if pending_count == 0:
            await bot.send_message(chat_id, "Нет вакансий в очереди на отклик.")
        else:
            await bot.send_message(
                chat_id,
                f"▶️ Возобновляю авто-отклики. В очереди: {pending_count} вакансий.",
            )
    except Exception:
        logger.exception("Failed to send resume_apply notification")
