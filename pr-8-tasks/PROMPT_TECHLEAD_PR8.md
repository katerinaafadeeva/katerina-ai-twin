# ПРОМПТ ДЛЯ ТЕХЛИДА — PR-8: Playwright Auto-Apply

## Инструкция для Катерины

Ниже — полный промпт для Claude Code (Sonnet).
3 фазы: Реализация → QA → Подготовка к merge.
После выполнения — только `git merge pr-8` в main.

**⚠️ PREREQS (перед запуском промпта):**
1. `pip install playwright --break-system-packages && playwright install chromium`
2. Убедись что HH аккаунт работает в браузере на этой машине
3. PR-7 вмержен в main, ~225 тестов проходят

---

## ПРОМПТ (копировать целиком в Claude Code)

```
Ты — техлид проекта AI Twin Career OS. Работаешь в ветке pr-8.
Язык всех объяснений, комментариев и отчётов: РУССКИЙ.

=== КОНТЕКСТ ===

PR-1..PR-7 вмержены в main. ~225 тестов проходят.
PR-8 добавляет автоматические отклики на HH.ru через Playwright.
Это ПОСЛЕДНИЙ PR до MVP v1. После merge — MVP v1 ЗАКРЫТ.

Репозиторий: https://github.com/katerinaafadeeva/katerina-ai-twin
Ветка: pr-8 (создай от main)

=== КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ===

1. НЕ трогай engine.py (policy engine). Ни одной строки.
2. НЕ трогай handler.py (scoring handler). Ни одной строки.
3. НЕ трогай generator.py (cover letter generator). Ни одной строки.
4. НОЛЬ новых LLM вызовов. PR-8 — чистый execution.
5. Feature flag HH_APPLY_ENABLED=false по умолчанию.
6. ВСЕ browser-операции в try/except. Ошибка apply НЕ крашит бота.
7. identity/hh_storage_state.json — в .gitignore (уже есть).
8. НЕ логировать cookies, headers, credentials.

=== ФАЗА 1: РЕАЛИЗАЦИЯ ===

Прочитай перед началом:
- DECISIONS.md
- capabilities/career_os/skills/match_scoring/worker.py (паттерн worker)
- capabilities/career_os/skills/cover_letter/store.py (паттерн store)
- core/config.py
- core/events.py

Выполни шаги из TASK_PR8_IMPLEMENTATION.md (он уже предоставлен или будет предоставлен).

Краткий план (9 шагов = 9 коммитов):

1. Миграция 008 — execution_status, execution_error, execution_attempts, applied_at, hh_vacancy_id в actions
2. Config — HH_APPLY_ENABLED, APPLY_DAILY_CAP, delays, batch size, storage state path
3. HH Browser connector — client.py (singleton), selectors.py, apply_flow.py, bootstrap.py
4. HH Apply skill store — get_pending_tasks, update_status, daily_count, extract_vacancy_id
5. HH Apply worker — async cycle: pick tasks → browser → update DB → emit events → notify
6. Telegram интеграция — worker как asyncio.Task за feature flag, /resume_apply команда
7. Notifier — TG уведомления для manual_required, captcha, session_expired, batch summary
8. Тесты — ≥25 новых (store, worker, apply flow), ALL mocked (no real Playwright)
9. Документация — STATUS (MVP v1 COMPLETE), CHANGELOG, DECISIONS, BACKLOG

Стратегия коммитов:
- feat(core): migration 008 — execution tracking fields in actions
- feat(core): add HH apply config — feature flag, caps, delays
- feat(connectors): add HH browser connector — client, selectors, apply flow, bootstrap
- feat(career_os): add hh_apply skill — store with task queue and execution status
- feat(career_os): add hh_apply worker — browser-based apply with cap, delays, notifications
- feat(bot): integrate apply worker — feature flag, /resume_apply, notifications
- feat(career_os): add apply notifier — TG notifications for all apply outcomes
- test: add hh_apply tests — store, worker, apply flow (all mocked)
- docs: update STATUS, CHANGELOG, DECISIONS, BACKLOG for PR-8 — MVP v1 complete

После каждого коммита: python3 -m pytest -q (все тесты зелёные)

=== ФАЗА 2: QA ===

После завершения, выполни QA-проверку:

1. РЕГРЕССИЯ:
   python3 -m pytest -q
   # Все ~225 существующих тестов + ~30 новых = ~255 total

   git diff main -- capabilities/career_os/skills/apply_policy/engine.py
   # ПУСТО

   git diff main -- capabilities/career_os/skills/match_scoring/handler.py
   # ПУСТО

   git diff main -- capabilities/career_os/skills/cover_letter/generator.py
   # ПУСТО

2. FEATURE FLAG:
   # При HH_APPLY_ENABLED=false worker НЕ запускается
   # Проверь что нет import playwright на уровне модуля (lazy import)

3. SECURITY:
   - grep -r "cookie\|token\|password" connectors/hh_browser/ (только комментарии, не значения)
   - identity/hh_storage_state.json в .gitignore
   - Никаких hardcoded credentials

4. ZERO LLM:
   git diff main -- connectors/ capabilities/career_os/skills/hh_apply/ | grep -i "anthropic\|llm\|haiku\|claude"
   # ПУСТО (кроме комментариев/docs)

5. ANTI-BAN:
   - Random delay между apply (config.apply_delay_min..max)
   - Batch size ограничен
   - Daily cap проверяется ДО получения задач
   - User-Agent реалистичный
   - Captcha → СТОП всего batch

6. ЧЕКЛИСТ:
   - [ ] Все тесты зелёные
   - [ ] Новых тестов ≥ 25
   - [ ] engine.py не тронут
   - [ ] handler.py не тронут
   - [ ] generator.py не тронут
   - [ ] Zero LLM calls
   - [ ] Feature flag работает
   - [ ] Миграция 008 работает
   - [ ] .gitignore правильный
   - [ ] .env.example обновлён
   - [ ] Selectors в отдельном файле
   - [ ] Bootstrap script создан
   - [ ] /resume_apply зарегистрирован
   - [ ] STATUS.md: MVP v1 COMPLETE
   - [ ] CHANGELOG, DECISIONS, BACKLOG обновлены
   - [ ] SKILL.md создан
   - [ ] Нет print() в production коде

=== ФАЗА 3: ОТЧЁТ ===

Подготовь финальный отчёт на РУССКОМ:

## Отчёт техлида: PR-8 Playwright Auto-Apply

### Статус: ✅ ГОТОВО К MERGE / ❌ ТРЕБУЕТ ДОРАБОТКИ

### 1. Реализовано
(файлы, таблицы, события, конфиг)

### 2. Файлы
| Файл | Тип | Описание |
|------|-----|----------|
| ... | new/changed | ... |

### 3. Тесты
Всего: N | Новых: N | Упавших: 0

### 4-7. Подтверждения
- engine.py: не тронут ✅
- handler.py: не тронут ✅
- generator.py: не тронут ✅
- Zero LLM calls: ✅
- Feature flag: ✅

### 8. Anti-ban
- Random delays: ✅
- Daily cap: ✅
- Batch size: ✅

### 9. Статистика
Новых файлов: N | Изменённых: N | Строк: +N/-N

### 10. git diff --stat main
(вставить)

### 11. TODO для post-MVP
- Auto-retry с backoff
- Screenshots при ошибках
- Docker support
- Random mouse movements
- TG inline кнопка "капча решена"

### 12. MVP v1 STATUS
✅ MVP v1 COMPLETE: PR-1..PR-8 merged
End-to-end: HH → Ingest → Score → Policy → Cover Letter → Apply → ✅

### 13. Рекомендация
✅ Готово к merge / ❌ Требует доработки
```

---

## ПОСЛЕ ПОЛУЧЕНИЯ ОТЧЁТА

1. **Если "✅ ГОТОВО К MERGE":**
   ```bash
   git checkout main
   git merge pr-8 --no-ff -m "PR-8: Playwright Auto-Apply — MVP v1 COMPLETE 🎉"
   python3 -m pytest -q
   git push origin main
   ```

2. **Если "❌ ТРЕБУЕТ ДОРАБОТКИ"** — отправь отчёт мне (Opus) для разбора.

3. **После merge PR-8** — 🎉 MVP v1 ЗАКРЫТ. Приходи ко мне за планом Итерации 2 (Web UI + API).

---

## ПЕРВЫЙ ЗАПУСК ПОСЛЕ MERGE

```bash
# 1. Установка Playwright
pip install playwright --break-system-packages
playwright install chromium

# 2. Bootstrap — авторизация на HH.ru (один раз)
python -m connectors.hh_browser.bootstrap
# Откроется браузер → войди в HH → нажми Enter

# 3. Включить auto-apply
# В .env: HH_APPLY_ENABLED=true

# 4. Запустить бота
python connectors/telegram_bot.py

# 5. Проверить
# - HH ingest заливает вакансии
# - Scoring оценивает
# - Policy маршрутизирует
# - Cover letter генерируется
# - Apply worker откликается автоматически
# - Telegram показывает summary
```
