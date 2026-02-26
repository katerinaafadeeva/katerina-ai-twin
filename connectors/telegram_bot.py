import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, MessageOriginChannel

from core.config import config
from core.db import get_conn, init_db
from core.security import is_authorized
from capabilities.career_os.skills.vacancy_ingest_telegram.handler import ingest
from capabilities.career_os.skills.match_scoring.worker import scoring_worker
from capabilities.career_os.skills.vacancy_ingest_hh.worker import hh_ingest_worker
from capabilities.career_os.skills.hh_apply.worker import hh_apply_worker
from capabilities.career_os.skills.hh_apply.store import get_pending_apply_tasks
from capabilities.career_os.skills.hh_apply.notifier import notify_resume_apply
from capabilities.career_os.skills.control_plane.handlers import (
    cmd_limits,
    cmd_stats,
    cmd_today,
    handle_approval_callback,
)

dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not is_authorized(message):
        return
    await message.answer(
        "Привет! Перешли мне пост с вакансией, и я её сохраню."
    )


@dp.message(F.forward_origin)
async def handle_forward(message: Message) -> None:
    if not is_authorized(message):
        return
    raw_text = message.text or message.caption
    if not raw_text:
        await message.answer("Не удалось прочитать текст поста.")
        return

    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        source_message_id = f"{origin.chat.id}_{origin.message_id}"
    else:
        source_message_id = f"msg_{message.message_id}"

    job_raw_id, is_new = ingest(
        raw_text=raw_text,
        source="telegram_forward",
        source_message_id=source_message_id,
    )

    if is_new:
        await message.answer(f"Сохранено: #{job_raw_id}")
    else:
        await message.answer(f"Уже в базе: #{job_raw_id}")


async def cmd_hh_login_help(message: Message) -> None:
    """/hh_login and /hh_login_help — HH.ru session status and bootstrap instructions.

    Does NOT open a browser. Headless=False is only possible locally via bootstrap.py.
    """
    if not is_authorized(message):
        return

    storage_path = config.hh_storage_state_path
    file_exists = os.path.exists(storage_path)
    apply_enabled = config.hh_apply_enabled

    status_line = (
        f"✅ Файл сессии найден: {storage_path}"
        if file_exists
        else f"❌ Файл сессии отсутствует: {storage_path}"
    )
    apply_line = (
        "✅ включены (HH_APPLY_ENABLED=true)"
        if apply_enabled
        else "⚠️ выключены (HH_APPLY_ENABLED=false — включите после авторизации)"
    )

    text = (
        f"🔑 Авторизация HH.ru\n\n"
        f"Статус: {status_line}\n"
        f"Авто-отклики: {apply_line}\n\n"
        f"Как создать/обновить сессию:\n"
        f"1. Остановите бота (Ctrl+C)\n"
        f"2. В терминале выполните:\n"
        f"   python -m connectors.hh_browser.bootstrap\n"
        f"3. В открывшемся браузере войдите на hh.ru\n"
        f"4. Нажмите Enter в терминале\n"
        f"5. В .env установите HH_APPLY_ENABLED=true\n"
        f"6. Запустите бота снова\n\n"
        f"Сессия действует 2-4 недели.\n"
        f"При истечении бот пришлёт уведомление с этой инструкцией."
    )
    await message.answer(text)


async def cmd_resume_apply(message: Message, bot: Bot) -> None:
    """/resume_apply — show queue size and trigger immediate apply cycle."""
    if not is_authorized(message):
        return
    if not config.allowed_telegram_ids:
        return
    chat_id = config.allowed_telegram_ids[0]

    with get_conn() as conn:
        pending = get_pending_apply_tasks(conn, limit=100)

    await notify_resume_apply(bot, chat_id, len(pending))

    if pending and config.hh_apply_enabled:
        from capabilities.career_os.skills.hh_apply.worker import _run_apply_cycle
        asyncio.create_task(_run_apply_cycle(bot))


async def main() -> None:
    init_db()
    bot = Bot(token=config.bot_token)

    # Proper async closure — lambda is NOT a coroutine function, so aiogram
    # would never await the returned coroutine, causing RuntimeWarning.
    async def _handle_resume_apply(message: Message) -> None:
        await cmd_resume_apply(message, bot)

    # Operator commands
    dp.message.register(cmd_today, Command("today"))
    dp.message.register(cmd_limits, Command("limits"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_hh_login_help, Command("hh_login"))
    dp.message.register(cmd_hh_login_help, Command("hh_login_help"))
    dp.message.register(_handle_resume_apply, Command("resume_apply"))

    # Inline button callbacks (approve/reject/snooze)
    dp.callback_query.register(handle_approval_callback)

    asyncio.create_task(scoring_worker(bot))
    # Start HH ingest worker (no-op if HH_ENABLED=false)
    asyncio.create_task(hh_ingest_worker())
    # Start HH apply worker (no-op if HH_APPLY_ENABLED=false)
    asyncio.create_task(hh_apply_worker(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
