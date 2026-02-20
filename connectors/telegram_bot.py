import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, MessageOriginChannel

from core.config import config
from core.db import init_db
from core.security import is_authorized
from capabilities.career_os.skills.vacancy_ingest_telegram.handler import ingest
from capabilities.career_os.skills.match_scoring.worker import scoring_worker

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


async def main() -> None:
    init_db()
    bot = Bot(token=config.bot_token)
    asyncio.create_task(scoring_worker(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
