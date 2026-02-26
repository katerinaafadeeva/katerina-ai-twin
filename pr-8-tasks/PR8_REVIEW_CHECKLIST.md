# ЧЕКЛИСТ MERGE — PR-8: Playwright Auto-Apply

**Дата:** 2026-02-25
**Кто заполняет:** Техлид (Claude Code / Sonnet)
**Когда:** ПОСЛЕ выполнения TASK + QA Gate

---

## Перед merge в main — пройти ВСЕ пункты

### 🔴 Блокирующие

- [ ] `python3 -m pytest -q` — ВСЕ тесты зелёные (0 failures)
- [ ] Новых тестов ≥ 25 (store + worker + apply flow)
- [ ] engine.py НЕ тронут
- [ ] handler.py (scoring) НЕ тронут
- [ ] generator.py (cover letter) НЕ тронут
- [ ] Worker НЕ запускается при HH_APPLY_ENABLED=false
- [ ] Migration 008 применяется: `python -c "from core.db import init_db; init_db(); print('OK')"`
- [ ] Никаких LLM вызовов в PR-8 коде
- [ ] Credentials/cookies НЕ в логах
- [ ] identity/hh_storage_state.json в .gitignore
- [ ] Все browser operations в worker обёрнуты в try/except

### 🟡 Важные

- [ ] STATUS.md: PR-8 ✅ DONE, MVP v1 ✅ COMPLETE
- [ ] CHANGELOG.md содержит PR-8
- [ ] DECISIONS.md содержит PR-8 Decisions
- [ ] BACKLOG.md: PR-8 DONE
- [ ] SKILL.md в hh_apply/
- [ ] .env.example обновлён
- [ ] Selectors в отдельном файле (не hardcoded в apply_flow)
- [ ] Bootstrap script работает
- [ ] /resume_apply команда зарегистрирована

### 🟢 Финальная проверка

- [ ] `git diff --stat main` — нет случайных файлов
- [ ] Все коммиты с осмысленными сообщениями
- [ ] Нет print() в production коде
- [ ] Нет hardcoded API keys/URLs с токенами

---

## Команда merge

```bash
git branch --show-current
# pr-8

python3 -m pytest -q

git checkout main
git merge pr-8 --no-ff -m "PR-8: Playwright Auto-Apply — MVP v1 COMPLETE 🎉"

python3 -m pytest -q
python -c "from core.db import init_db; init_db(); print('Post-merge OK')"
```

---

## MVP v1 — ФИНАЛЬНАЯ КАРТА

| PR | Статус | Что делает |
|----|--------|-----------|
| PR-1 | ✅ merged | Database, migrations, events |
| PR-2 | ✅ merged | Telegram ingest + dedup |
| PR-3 | ✅ merged | LLM scoring (Claude Haiku, 0-10) |
| PR-4 | ✅ merged | Policy engine (routing) |
| PR-5 | ✅ merged | Approval UX (Telegram buttons) |
| PR-6 | ✅ merged | HH.ru ingest (anonymous API) |
| PR-7 | ✅ merged | Cover letter generation (LLM + fallback) |
| **PR-8** | **✅ merged** | **Playwright auto-apply** |

### 🎉 MVP v1 = COMPLETE

End-to-end:
```
HH vacancy → Ingest → Score (LLM) → Policy → Cover Letter (LLM) → Auto-Apply (Playwright) → ✅
                                            ↗ Approval (TG) → Approve → Apply → ✅
```

### Что дальше

| Итерация | Что | PRs |
|----------|-----|-----|
| 2 | Web UI + API | PR-9+ |
| 3 | Analytics + Notion | PR-12+ |
| 4 | Personal OS | PR-14+ |
