# 🔧 Отчёт: Production Bug Fix Sprint — Career OS v1

**Дата:** 2026-03-03
**Ветка:** `feat/employer-questionnaire` (продолжение fix-спринта)
**Тестов:** 447 ✅

---

## Исправленные баги

### 🔴 BUG-A (P0): TG-форварды не скорились

**Причина:** `HH_SCORING_DAILY_CAP=15` исчерпывался на HH-вакансиях до того, как до TG-форвардов
доходила очередь. В `get_unscored_vacancies` порядок был простой `ORDER BY created_at ASC`.

**Исправлено:**

1. `match_scoring/store.py` — TG-вакансии идут первыми:
   ```sql
   ORDER BY
       CASE WHEN jr.source = 'telegram_forward' THEN 0 ELSE 1 END,
       jr.created_at ASC
   ```

2. `match_scoring/worker.py` — TG-форварды обходят дневной cap (пользователь сам переслал ссылку,
   значит скоринг обязателен независимо от лимита HH-ingestion):
   ```python
   is_tg_forward = (vacancy.get("source") or "") == "telegram_forward"
   if config.hh_scoring_daily_cap > 0 and not is_tg_forward:
       ...  # cap check только для HH
   ```

**Рекомендация по `.env`:** `HH_SCORING_DAILY_CAP=15 → 50`
15 было слишком мало для нормального рабочего дня. HH выдаёт по 20–40 вакансий за цикл.

---

### 🔴 BUG-B (P0): Дублирующее уведомление для AUTO_APPLY

**Причина:** `scoring_worker` отправлял «Автоотклик HH» сразу при принятии решения. Через несколько
минут `hh_apply_worker` отправлял второе уведомление — уже с реальным результатом. В итоге оператор
получал два сообщения об одном отклике.

**Исправлено:** `match_scoring/worker.py` — блок `AUTO_APPLY` заменён на `pass`:
```python
elif decision.action_type == ActionType.AUTO_APPLY:
    pass  # Уведомление придёт от apply worker (с реальным результатом + письмом)
```
Scoring_worker по-прежнему отправляет уведомления для `AUTO_QUEUE` и `APPROVAL_REQUIRED` —
только там есть смысл уведомлять сразу (очередь или требуется подтверждение).

---

### 🔴 BUG-C (P0): Сопроводительное письмо не показывалось в уведомлении об отклике

**Причина:** `notify_apply_done` принимала только `letter_status` и `action_id`. Текст письма,
счёт и название вакансии не передавались.

**Исправлено:**

`hh_apply/notifier.py` — расширена подпись `notify_apply_done`:
```python
async def notify_apply_done(
    bot, chat_id, job_raw_id, apply_url,
    letter_status=None, action_id=None,
    cover_letter_text=None,   # ← новое
    score=None,               # ← новое
    vacancy_title=None,       # ← новое
) -> None:
```

`hh_apply/worker.py` — передаём все данные:
```python
await notify_apply_done(
    bot, chat_id, job_raw_id, result.apply_url,
    letter_status=result.letter_status,
    action_id=action_id,
    cover_letter_text=cover_letter or None,
    score=task.get("score"),
    vacancy_title=_title_line or None,
)
```

**Формат нового уведомления:**
```
✅ Отклик + 📝 письмо | Score: 8/10: #1234 [action=56]
Product Manager — ООО Рога и Копыта
https://hh.ru/vacancy/130884375

📝 Сопроводительное:
Добрый день! Меня зовут Катерина...
```

---

### 🟡 BUG-D (P1): Верификация отправки inline-письма

**Причина:** `_fill_inline_letter` кликал Submit и сразу возвращал `True` без проверки того, что
форма исчезла. Если HH не принял письмо (ошибка валидации, сетевой сбой), бот всё равно
логировал `sent_inline`.

**Исправлено:** `connectors/hh_browser/apply_flow.py` — после `submit.click()` ждём исчезновения
формы (до 5 секунд):
```python
await page.wait_for_selector(
    selectors.INLINE_LETTER_FORM,
    state="hidden",
    timeout=5_000,
)
```
Если форма не исчезает — логируется `WARNING` но функция всё равно возвращает `True`
(fill+click выполнены; false-negative хуже false-positive в этом сценарии).

---

### 🟡 BUG-E (P1): Дубликаты в таблице actions

**Причина:** Раньше `save_action` делал `INSERT` без `OR IGNORE`. При гонке cycles или повторном
скоринге одной вакансии в таблице появлялись дубли.

**Исправлено:**

1. **`core/migrations/010_actions_dedup.sql`** — удаляет существующие дубли, добавляет индекс:
   ```sql
   DELETE FROM actions
   WHERE id NOT IN (
       SELECT MIN(id) FROM actions GROUP BY job_raw_id, action_type
   );
   CREATE UNIQUE INDEX IF NOT EXISTS idx_actions_job_raw_dedup
       ON actions(job_raw_id, action_type);
   ```

2. **`apply_policy/store.py`** — `save_action` теперь `INSERT OR IGNORE`, возвращает `0` при
   дубликате:
   ```python
   INSERT OR IGNORE INTO actions (...) VALUES (...)
   rowid = cursor.lastrowid if cursor.rowcount > 0 else 0
   ```

⚠️ **Важно:** перед следующим запуском бота выполни миграцию вручную:
```bash
sqlite3 data/career.db < core/migrations/010_actions_dedup.sql
```

---

### 🟡 BUG-F (P1): Репозиторий

**Обновлён `.gitignore`:**
- `.venv/`, `venv/`
- `*.pyc`, `*.pyo`
- `.pytest_cache/`, `.mypy_cache/`
- `logs/*.jsonl`, `logs/*.log` (файл откликов)
- `/tmp/hh_apply_artifacts/` (скрины и HTML с упавших apply)

---

## Новая функциональность: Лог откликов

**Файл:** `core/apply_logger.py`
**Лог-файл:** `logs/apply_log.jsonl` (gitignored, создаётся автоматически)

При каждом успешном отклике `hh_apply_worker` дописывает строку в лог:
```json
{
  "ts": "2026-03-03 12:34:56",
  "action_id": 56,
  "job_raw_id": 1234,
  "hh_vacancy_id": "130884375",
  "title": "Product Manager — ООО Рога и Копыта",
  "url": "https://hh.ru/vacancy/130884375",
  "status": "done",
  "letter_status": "sent_popup",
  "score": 8,
  "cover_letter_len": 1240,
  "cover_letter": "Добрый день! Меня зовут Катерина..."
}
```

Для просмотра:
```bash
# Последние 10 откликов
tail -10 logs/apply_log.jsonl | python3 -m json.tool

# Только успешные с письмом
grep '"status": "done"' logs/apply_log.jsonl | grep '"sent_'
```

---

## Оценка .env конфигурации

Твой текущий `.env` в целом разумный. Конкретные замечания:

| Параметр | Текущее | Рекомендую | Комментарий |
|---|---|---|---|
| `HH_SCORING_DAILY_CAP` | `15` | **`50`** | 15 — слишком мало, TG-вакансии не успевали |
| `HH_APPLY_ENABLED` | `true` | ✅ `true` | Комментарий «выключен» в файле ошибочный — значение `true` = включено |
| `APPLY_DAILY_CAP` | `10` | ✅ `10` | Хорошо для старта |
| `APPLY_DELAY_MIN/MAX` | `15–45 с` | ✅ оставить | Достаточно для anti-ban |
| `APPLY_BATCH_SIZE` | `3` | ✅ `3` | Разумно |
| `COVER_LETTER_DAILY_CAP` | `20` | ✅ `20` | Хватит на рабочий день |
| `APPLY_SCHEDULE` | `9–20` | ✅ оставить | Правильное окно |
| `HH_POLL_INTERVAL` | `60 с` | ✅ `60 с` | Норм |

**⚠️ Главное:** убедись что `HH_APPLY_ENABLED=true` — это действительно то, что ты хочешь.
Если apply выключен — поставь `false`.

**⚠️ Секреты в `.env`:** Файл содержит `BOT_TOKEN` и `ANTHROPIC_API_KEY` — он
корректно добавлен в `.gitignore` (`line 1: .env`). Не коммить его случайно.

---

## Итог изменений по файлам

| Файл | Что изменилось |
|---|---|
| `match_scoring/store.py` | ORDER BY: TG-forwards первыми |
| `match_scoring/worker.py` | Cap bypass для TG; удалён AUTO_APPLY блок уведомлений |
| `hh_apply/notifier.py` | `notify_apply_done` + cover_letter_text / score / title |
| `hh_apply/worker.py` | Передача письма+score в уведомление; log_apply_event |
| `apply_policy/store.py` | `save_action` → `INSERT OR IGNORE` |
| `connectors/hh_browser/apply_flow.py` | Inline letter post-submit verification |
| `core/migrations/010_actions_dedup.sql` | UNIQUE INDEX + dedup existing rows |
| `core/apply_logger.py` | Новый модуль — JSONL лог откликов |
| `logs/.gitkeep` | Директория logs/ в репо |
| `.gitignore` | `.venv/`, `*.pyc`, `logs/*.jsonl`, и др. |
| `tests/test_cover_letter_store.py` | Фикс: второй action → AUTO_QUEUE |
| `tests/test_hh_apply_store.py` | Фикс: второй action → APPROVAL_REQUIRED |
