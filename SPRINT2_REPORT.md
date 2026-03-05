# SPRINT 2 — Post-Launch Fixes + UX Improvements

**Дата:** 05.03.2026
**Ветка:** `fix/scoring-cap-split-and-apply-guard`
**Тесты:** 479 passed (было 447 → +32 новых)

---

## ISSUE-1 (P0): Раздельные капы HH + TG ✅

**Проблема:** Единый лимит `HH_SCORING_DAILY_CAP=40` исчерпывался HH-вакансиями. При этом ручные форварды из TG тоже блокировались. Корневая причина: Sprint-1 BUG-A использовал `break` вместо `continue` при исчерпании лимита.

**Изменения:**

| Файл | Что сделано |
|------|-------------|
| `core/config.py` | Добавлен `tg_scoring_daily_cap: int` (env `TG_SCORING_DAILY_CAP`, default 20) |
| `vacancy_ingest_hh/store.py` | Добавлены `get_today_scored_count_by_source(conn, source)` и `was_tg_scoring_cap_notification_sent_today(conn)` |
| `match_scoring/worker.py` | Заменён `is_tg_forward`+`break` на два независимых `continue`-блока: HH-кап и TG-кап |
| `control_plane/store.py` | `get_today_summary()` возвращает `hh_scored_today` и `tg_scored_today` |
| `control_plane/handlers.py` | Добавлена `_pbar()` helper, обе капы с прогресс-барами в `/today` и `/stats` |
| `.env` | `TG_SCORING_DAILY_CAP=20` |
| `.env.example` | `TG_SCORING_DAILY_CAP=20` |

**Поведение теперь:** TG-форвард оценивается даже при исчерпанном HH-лимите, и наоборот. Уведомления о капах приходят отдельно для HH и TG.

---

## ISSUE-2 (P0): Проверка «уже откликнулись» ✅

**Проблема:** Scoring worker мог создавать новое AUTO_APPLY-действие для вакансии, на которую уже был отправлен отклик.

**Изменения:**

| Файл | Что сделано |
|------|-------------|
| `apply_policy/store.py` | Добавлена `has_successful_apply_for_job(conn, job_raw_id) -> bool` — проверяет `apply_runs` с `status IN ('done', 'done_without_letter')` |
| `match_scoring/worker.py` | Перед `save_action` для AUTO_APPLY проверяется `has_successful_apply_for_job`; при `True` — `continue` (действие не создаётся) |

---

## ISSUE-3 (P2): Команда `/letter` ✅

**Что добавлено:** Команда `/letter <action_id>` показывает сопроводительное письмо для ручного копипаста в чат HH.

**Файл:** `connectors/telegram_bot.py`
- Новый обработчик `cmd_letter(message)` — парсит `action_id`, вызывает `get_cover_letter_for_action`, отвечает текстом письма (с обрезкой до 4096 символов)

---

## ISSUE-4 (P2): UX-улучшения ✅

**Что добавлено:**

| Функция | Описание |
|---------|----------|
| `/queue` | Показывает очередь AUTO_APPLY-откликов (до 20 задач): action_id, score, название, URL |
| `/today` и `/stats` | Прогресс-бары `_pbar()` для HH-скоринга, TG-скоринга и откликов |
| `handle_forward` | После сохранения форварда — статус TG-капы: "⏳ Оценка через ~1-2 мин (X/20)" или "⏸ TG-лимит исчерпан (20/20)" |
| `/help` | Добавлены `/queue` и `/letter` в список команд |

---

## Тесты (+32 новых)

| Файл | Покрытие |
|------|----------|
| `test_scoring_cap_split.py` | `get_today_scored_count_by_source`, `was_tg_scoring_cap_notification_sent_today`, 4 сценария worker-капы |
| `test_apply_guard.py` | `has_successful_apply_for_job` (6 store-тестов), 2 worker-теста guard |
| `test_letter_queue_ux.py` | `_pbar` (8 тестов), `get_cover_letter_for_action` (2), `/queue` pending tasks (3) |

Дополнительно исправлены 2 существующих теста в `test_regression_fixes.py` — добавлены `hh_scoring_daily_cap` и `tg_scoring_daily_cap` в mock config.

**Итого: 479 passed, 0 failed.**
