# ЧЕКЛИСТ MERGE — PR-7: Cover Letter Generation

**Дата:** 2026-02-25
**Кто заполняет:** Техлид (Claude Code / Sonnet)
**Когда:** ПОСЛЕ выполнения TASK + QA Gate

---

## Перед merge в main — пройти ВСЕ пункты

### 🔴 Блокирующие (merge невозможен если ❌)

- [ ] `python3 -m pytest -q` — ВСЕ тесты зелёные (0 failures)
- [ ] Новых тестов ≥ 20 (cover letter store + generator + prompt)
- [ ] `git diff main -- capabilities/career_os/skills/apply_policy/engine.py` — ПУСТО
- [ ] `git diff main -- capabilities/career_os/skills/match_scoring/handler.py` — ПУСТО
- [ ] Cover letter в worker.py обёрнут в try/except (если CL падает, scoring работает)
- [ ] `python -c "from core.db import init_db; init_db(); print('OK')"` — миграция 007 работает
- [ ] Fallback работает при отсутствии файла `identity/cover_letter_fallback.txt`
- [ ] `identity/cover_letter_fallback.txt` в `.gitignore`
- [ ] `identity/cover_letter_fallback.example.txt` committed

### 🟡 Важные (должны быть, но не блокируют при обосновании)

- [ ] `STATUS.md` обновлён: PR-7 ✅ DONE
- [ ] `CHANGELOG.md` содержит секцию PR-7
- [ ] `DECISIONS.md` содержит PR-7 Decisions
- [ ] `BACKLOG.md`: PR-7 DONE, PR-8 NEXT
- [ ] `SKILL.md` в `capabilities/career_os/skills/cover_letter/`
- [ ] `.env.example` содержит COVER_LETTER_DAILY_CAP и COVER_LETTER_FALLBACK_PATH
- [ ] APPROVAL_REQUIRED Telegram card показывает cover letter preview (≤200 chars)
- [ ] AUTO_APPLY уведомление упоминает "сопроводительное"
- [ ] Prompt `cover_letter_v1.py` содержит STRICT RULES (prompt injection defense)

### 🟢 Финальная проверка

- [ ] `git diff --stat main` — проверить что нет случайных файлов
- [ ] Все коммиты с осмысленными сообщениями (feat/test/docs)
- [ ] Нет `print()` в production коде (только logger)
- [ ] Нет hardcoded API keys
- [ ] Нет `TODO` или `FIXME` без ticket/issue ссылки

---

## Команда merge

```bash
# Убедиться что на ветке pr-7
git branch --show-current
# pr-7

# Финальный прогон тестов
python3 -m pytest -q

# Merge
git checkout main
git merge pr-7 --no-ff -m "PR-7: Cover Letter Generation (LLM + fallback) — MVP v1"

# Проверка после merge
python3 -m pytest -q
python -c "from core.db import init_db; init_db(); print('Post-merge OK')"
```

---

## После merge — что дальше

| Шаг | Действие |
|-----|----------|
| 1 | PR-7 смержен → MVP v1 cover letter ready |
| 2 | PR-8: Playwright auto-apply (последний PR до MVP v1) |
| 3 | После PR-8 → MVP v1 ЗАКРЫТ |
| 4 | Итерация 2: Web UI (PR-9+) |

---

## MVP v1 статус после PR-7

| PR | Статус | Что делает |
|----|--------|-----------|
| PR-1 | ✅ merged | Database, migrations, events |
| PR-2 | ✅ merged | Telegram ingest + dedup |
| PR-3 | ✅ merged | LLM scoring (Claude Haiku, 0-10) |
| PR-4 | ✅ merged | Policy engine (IGNORED/AUTO_APPLY/HOLD/APPROVAL_REQUIRED) |
| PR-5 | ✅ merged | Approval UX (Telegram buttons) |
| PR-6 | ✅ merged | HH.ru ingest (anonymous API + prefilter + scoring cap) |
| **PR-7** | **🔄 текущий** | **Cover letter generation (LLM + fallback)** |
| PR-8 | ⏳ next | Playwright auto-apply (browser automation) |

**MVP v1 = PR-1..PR-8. После PR-8 → MVP v1 закрыт.**
