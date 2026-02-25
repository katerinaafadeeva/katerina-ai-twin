# ПРОМПТ ДЛЯ ТЕХЛИДА — PR-7: Cover Letter Generation

## Инструкция для Катерины

Ниже — полный промпт, который нужно вставить в Claude Code (модель: Sonnet).
Промпт содержит 3 фазы: Реализация → QA → Подготовка к merge.
После выполнения всех фаз останется только `git merge pr-7` в main.

---

## ПРОМПТ (копировать целиком в Claude Code)

```
Ты — техлид проекта AI Twin Career OS. Работаешь в ветке pr-7.
Язык всех объяснений, комментариев и отчётов: РУССКИЙ.

=== КОНТЕКСТ ===

PR-6 (HH Ingest v0.1) вмержен в main. 200 тестов проходят.
PR-7 добавляет генерацию сопроводительных писем (cover letter) для auto-apply flow через HH.ru.

Репозиторий: https://github.com/katerinaafadeeva/katerina-ai-twin
Ветка: pr-7 (создай от main)

=== ФАЗА 1: РЕАЛИЗАЦИЯ ===

Перед началом работы ОБЯЗАТЕЛЬНО прочитай эти файлы:
- DECISIONS.md
- capabilities/career_os/skills/match_scoring/worker.py
- core/llm/client.py
- core/config.py
- identity/profile.example.json

Затем выполни шаги из файла TASK_PR7_IMPLEMENTATION.md (он уже в репозитории или будет предоставлен).

Краткий план шагов:
1. Миграция 007 — таблица cover_letters (UNIQUE на job_raw_id + action_id)
2. Config — добавить cover_letter_daily_cap (default 50), cover_letter_fallback_path
3. Промпт — core/llm/prompts/cover_letter_v1.py (русский, 3-5 предложений, prompt injection defense)
4. Skill — capabilities/career_os/skills/cover_letter/ (store.py, generator.py, fallback.py, SKILL.md)
5. Интеграция — worker.py: генерация CL после save_action() для AUTO_APPLY и APPROVAL_REQUIRED
6. Approval callback — генерация CL при approve если ещё не существует
7. Тесты — ≥20 новых тестов (store, generator, prompt), mock Anthropic API
8. Документация — STATUS.md, CHANGELOG.md, DECISIONS.md, BACKLOG.md

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:
- НЕ трогай engine.py (policy engine). Ни одной строки.
- НЕ трогай handler.py (scoring handler). Ни одной строки.
- ВСЕ изменения cover letter в worker.py — в try/except. Ошибка CL не должна ломать scoring.
- Fallback ОБЯЗАН работать при отсутствии файла identity/cover_letter_fallback.txt
- identity/cover_letter_fallback.txt — в .gitignore (персональный тон)
- identity/cover_letter_fallback.example.txt — committed (шаблон)

Стратегия коммитов:
- feat(core): migration 007 — cover_letters table
- feat(core): add cover letter config, fallback template
- feat(core): add cover letter LLM prompt v1
- feat(career_os): add cover letter skill — store, generator, fallback
- feat(scoring): integrate cover letter generation into scoring worker
- feat(control_plane): generate cover letter on approval
- test: add cover letter store, generator, and prompt tests
- docs: update STATUS, CHANGELOG, DECISIONS, BACKLOG for PR-7

После каждого коммита: python3 -m pytest -q (все тесты должны быть зелёные)

=== ФАЗА 2: QA ===

После завершения реализации, выполни QA-проверку:

1. РЕГРЕССИЯ:
   python3 -m pytest -q
   # Все 200+ существующих тестов проходят

   git diff main -- capabilities/career_os/skills/apply_policy/engine.py
   # ПУСТО — engine.py не тронут

   git diff main -- capabilities/career_os/skills/match_scoring/handler.py
   # ПУСТО — handler.py не тронут

2. НОВАЯ ФУНКЦИОНАЛЬНОСТЬ:
   python -c "from core.db import init_db; init_db(); print('Migration OK')"
   python -c "from core.config import config; print('CL cap:', config.cover_letter_daily_cap)"
   python -c "
   from capabilities.career_os.skills.cover_letter.fallback import get_fallback_text
   text = get_fallback_text()
   assert len(text) > 20
   print('Fallback OK:', text[:60])
   "

3. SECURITY:
   - Проверь что cover letter text НЕ пишется в events (только в cover_letters table)
   - Проверь что profile проходит через prepare_profile_for_llm()
   - Проверь что vacancy text проходит через sanitize_for_llm()
   - Проверь что cover_letter_fallback.txt в .gitignore

4. ЧЕКЛИСТ (пройди каждый пункт):
   - [ ] Все тесты зелёные (0 failures)
   - [ ] Новых тестов ≥ 20
   - [ ] engine.py не тронут
   - [ ] handler.py не тронут
   - [ ] worker.py: CL в try/except
   - [ ] Миграция 007 работает
   - [ ] Fallback без файла работает
   - [ ] .gitignore содержит identity/cover_letter_fallback.txt
   - [ ] .example.txt committed
   - [ ] STATUS.md обновлён
   - [ ] CHANGELOG.md содержит PR-7
   - [ ] DECISIONS.md содержит PR-7
   - [ ] BACKLOG.md: PR-7 DONE
   - [ ] SKILL.md создан
   - [ ] .env.example обновлён
   - [ ] Нет print() в production коде
   - [ ] Нет hardcoded API keys

=== ФАЗА 3: ОТЧЁТ ===

После QA, подготовь финальный отчёт на РУССКОМ:

1. Что реализовано (файлы, таблицы, события)
2. Какие файлы созданы/изменены (список с кратким описанием)
3. Результаты тестов (вставь вывод pytest)
4. Подтверждение: policy rules НЕ изменены (engine.py untouched)
5. Подтверждение: scoring logic НЕ изменена (handler.py untouched)
6. Подтверждение: scoring worker изменения изолированы (try/except)
7. Подтверждение: fallback работает при отсутствии файла
8. Стоимость: оценка $/день при 50 письмах
9. Количество новых/изменённых файлов, строк кода
10. git diff --stat main
11. Риски или TODO для PR-8 (Playwright integration points)
12. Рекомендация: готово к merge ✅ / требует доработки ❌

Формат отчёта:

## Отчёт техлида: PR-7 Cover Letter Generation

### Статус: ✅ ГОТОВО К MERGE / ❌ ТРЕБУЕТ ДОРАБОТКИ

### 1. Реализовано
...

### 2. Файлы
| Файл | Тип | Описание |
|------|-----|----------|
| ... | new/changed | ... |

### 3. Тесты
Всего: N | Новых: N | Упавших: 0

### 4-7. Подтверждения
- engine.py: не тронут ✅
- handler.py: не тронут ✅
- worker.py: изолировано ✅
- fallback: работает ✅

### 8. Стоимость
~$X.XX/день при 50 письмах

### 9. Статистика
Новых файлов: N | Изменённых: N | Строк: +N/-N

### 10. git diff
(вставить)

### 11. TODO для PR-8
- ...

### 12. Рекомендация
✅ / ❌
```

---

## ПОСЛЕ ПОЛУЧЕНИЯ ОТЧЁТА ОТ ТЕХЛИДА

Катерина, когда техлид (Claude Code / Sonnet) пришлёт отчёт:

1. **Если "✅ ГОТОВО К MERGE"** — выполни:
   ```bash
   git checkout main
   git merge pr-7 --no-ff -m "PR-7: Cover Letter Generation (LLM + fallback) — MVP v1"
   python3 -m pytest -q  # контроль после merge
   git push origin main
   ```

2. **Если "❌ ТРЕБУЕТ ДОРАБОТКИ"** — отправь отчёт мне (Opus, Chief Architect) для разбора.

3. **После merge PR-7** — приходи ко мне за PR-8 (Playwright auto-apply). Это последний PR до MVP v1.

---

## КАРТА MVP v1

```
PR-1 ✅  Database + migrations + events
PR-2 ✅  Telegram ingest + dedup
PR-3 ✅  LLM scoring (Haiku, 0-10)
PR-4 ✅  Policy engine (routing)
PR-5 ✅  Approval UX (Telegram)
PR-6 ✅  HH.ru ingest (API + prefilter)
PR-7 🔄  Cover letter generation    ← ТЫ ЗДЕСЬ
PR-8 ⏳  Playwright auto-apply      ← ПОСЛЕДНИЙ

MVP v1 = PR-1..PR-8
После PR-8 → MVP v1 ЗАКРЫТ → Итерация 2 (Web UI)
```
