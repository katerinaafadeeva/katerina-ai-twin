# ADR-003: Event-Driven Worker Architecture

**Status:** Accepted
**Date:** 2026-02-20
**Decider:** Chief Architect (per Founder requirement)

## Context

Scoring НЕ должен быть inline в Telegram handler:
- LLM call занимает 1-5 секунд
- Telegram handler должен отвечать быстро ("сохранено")
- Scoring может упасть / retried / быть idempotent

## Decision

### Минимальный worker pattern (in-process)

НЕ отдельный процесс. НЕ Celery/Redis. Это in-process async worker на базе asyncio.

```
Telegram handler
  → ingest (sync, fast)
  → emit("vacancy.ingested")
  → reply "Сохранено ✅"

Background worker (asyncio.Task)
  → poll events where event_name = "vacancy.ingested" AND NOT scored
  → score (LLM call)
  → persist score
  → emit("vacancy.scored")
  → send Telegram notification (score result)
```

### Почему не отдельный процесс

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| In-process asyncio | Zero ops, shared bot instance, simple | Single point of failure |
| Separate worker + Redis | Isolation, scalability | Ops overhead, Redis dependency |
| Celery | Full queue semantics | Massive overhead для 50 tasks/day |

При 50 вакансий/день in-process asyncio — правильный выбор.
**Пересмотр:** если scoring queue > 500/day или нужен отдельный deployment.

### Idempotency

- Worker проверяет: `job_scores WHERE job_raw_id = ? AND scorer_version = ?`
- Если score уже есть → skip
- Если нет → score → persist
- Retry: если LLM call fails → event остаётся unprocessed → next poll picks up

### Worker Loop

```python
async def scoring_worker(bot: Bot, interval_seconds: int = 10):
    """Background worker: polls for unscored vacancies, scores them."""
    while True:
        try:
            unscored = get_unscored_vacancies()  # LEFT JOIN job_scores IS NULL
            for vacancy in unscored:
                try:
                    result = await score_vacancy(vacancy.raw_text, profile)
                    save_score(vacancy.id, result)
                    await notify_user(bot, vacancy.id, result)
                except LLMError:
                    logger.warning("scoring failed, will retry", job_raw_id=vacancy.id)
        except Exception:
            logger.exception("worker loop error")
        await asyncio.sleep(interval_seconds)
```

### Notification Flow

```
User forwards vacancy
  ↓
Bot: "Сохранено: #42 ✅"         ← immediate
  ↓  (5-10 seconds later)
Bot: "Оценка #42: 🟢 7.3/10     ← second message
      PM в fintech, удалёнка, 
      зарплата выше минимума."
```

## Consequences

- telegram_bot.py запускает worker как asyncio.Task при старте
- Worker делит event loop с aiogram (не блокирует)
- Scoring handler становится async (для LLM HTTP call)
- Нужен метод `get_unscored_vacancies()` в db layer
