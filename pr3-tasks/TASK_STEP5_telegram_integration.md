# TASK: PR-3 Step 5 — Telegram Integration + Worker Startup

## Role
You are the Implementation Agent (Tech Lead). Execute precisely.

## Context
PR-3, Step 5 of 7. Steps 1-4 complete. All code + tests exist.
Now integrate everything into the Telegram bot.

Read first:
- connectors/telegram_bot.py (current state)
- capabilities/career_os/skills/match_scoring/worker.py
- core/security.py
- core/config.py

## Deliverables

### 1. `connectors/telegram_bot.py` — Full rewrite

The file is small (~50 lines). Rewrite it to:

**Changes:**
1. Replace `os.environ["BOT_TOKEN"]` with `config.bot_token`
2. Remove `from dotenv import load_dotenv; load_dotenv()` (config.py handles it)
3. Add `is_authorized()` check to ALL handlers (cmd_start, handle_forward)
4. Remove scoring logic from handle_forward (scoring is async via worker)
5. handle_forward → ingest + reply "Сохранено: #{id} ✅" (no score)
6. Start `scoring_worker` as `asyncio.Task` in `main()`
7. Add basic logging setup
8. Add `/score` command — manually trigger re-scoring for a given vacancy (optional, nice-to-have)

**Target structure:**

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, MessageOriginChannel

from core.config import config
from core.db import init_db
from core.security import is_authorized
from capabilities.career_os.skills.vacancy_ingest_telegram.handler import ingest
from capabilities.career_os.skills.match_scoring.worker import scoring_worker

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not is_authorized(message):
        return
    await message.answer(
        "Привет! Перешли мне пост с вакансией, и я её сохраню и оценю."
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
        await message.answer(f"Сохранено: #{job_raw_id} ✅\nОценка будет через несколько секунд...")
    else:
        await message.answer(f"Уже в базе: #{job_raw_id}")


async def main() -> None:
    init_db()
    bot = Bot(token=config.bot_token)
    
    # Start scoring worker as background task
    asyncio.create_task(scoring_worker(bot))
    logger.info("Scoring worker scheduled")
    
    logger.info("Bot starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Verify end-to-end flow

After this step, the complete flow works:

```
1. User forwards vacancy to bot
2. Bot: "Сохранено: #42 ✅ Оценка будет через несколько секунд..."
3. ingest() saves to job_raw + emits vacancy.ingested
4. Worker (polling every 10s) finds unscored vacancy
5. Worker: sanitize → LLM call → validate → save to job_scores
6. Worker sends: "Оценка #42: 🟢 7.3/10\nХорошее совпадение: роль PM, удалёнка, навыки совпадают."
7. Events table has: vacancy.ingested + vacancy.scored + llm.call
```

## Constraints

- Keep the file simple and readable
- Auth check is FIRST thing in every handler
- Worker is fire-and-forget task (if it crashes, bot still works)
- No inline scoring — only via worker
- Logging on all important events

## How to verify

1. Set up `.env` with real BOT_TOKEN and ANTHROPIC_API_KEY
2. Fill `identity/profile.json` with real data
3. Run: `python connectors/telegram_bot.py`
4. Forward a vacancy to the bot
5. Expect: immediate "Сохранено" + delayed "Оценка" message
6. Check SQLite: job_raw has entry, job_scores has entry, events has 3 entries

## Commit message
```
feat(telegram): integrate scoring worker + auth into bot

- connectors/telegram_bot.py: auth whitelist, async worker startup
- Scoring decoupled from handler (worker sends second message)
- Logging setup with configurable level
```
