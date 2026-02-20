# PR-3 Review → PR-4 Plan → MVP Timeline

**Chief Architect Report**
**Date:** 2026-02-20

---

# PART 1: PR-3 Review Verdict

## Verdict: ✅ PASS

PR-3 реализован качественно. Вот файл-по-файл review:

### Что сделано правильно

| Компонент | Оценка | Комментарий |
|-----------|--------|-------------|
| Score contract 0–10 | ✅ | ADR-001 пересмотрен (отклонён 0–100), schema CHECK(0..10), Pydantic ge=0 le=10 |
| LLM client | ✅ | Async, audit в finally, cost tracking, code fence stripping |
| Sanitization | ✅ | Zero-width, control chars, truncation, PII allowlist |
| Worker pattern | ✅ | Async task, idempotent, LEFT JOIN, retry via fallback model |
| Auth | ✅ | is_authorized() в обоих handlers, dev mode warning |
| Migrations | ✅ | 3 файла, runner с tracking table, применяются по порядку |
| Tests | ✅ | 41 passed — schemas, sanitize, store, config |
| Prompt security | ✅ | `<vacancy>` tags, NEVER-follow rule, output validation |
| Documentation | ✅ | CHANGELOG, DECISIONS updated, ADRs 001-005 |

### Замечания (некритичные, fix в follow-up)

**[MEDIUM] `docs/` — stale documents**
`docs/CHAT_HANDOFF.md`, `docs/CHAT_SNAPSHOT.md`, `docs/TOKEN_BUDGET.md` содержат устаревшую информацию (ссылки на "heuristic-only", "no LLM for scoring"). Не блокирует, но создаёт путаницу.
→ Fix: обновить в PR-4 commit 1 (docs cleanup).

**[MEDIUM] `BACKLOG.md` — не синхронизирован с STATUS.md**
BACKLOG всё ещё показывает PR-3 как "NEXT", STATUS.md корректен.
→ Fix: sync в PR-4.

**[LOW] `telegram_bot.py` — нет logging.basicConfig**
Worker логирует, но формат не настроен. Логи уходят в default format.
→ Fix: добавить в PR-4 или PR-5.

**[LOW] `ADR-002` — оставлена строка "score 0-100" в таблице**
В "What LLM does" написано "Присваивает score 0-100" — артефакт предыдущей версии.
→ Fix: в PR-4 docs cleanup.

**Ни одного CRITICAL или HIGH issue. PR-3 merged correctly.**

---

# PART 2: PR-4 — Policy Engine

## 2.1 Founder Brief (как я его понимаю)

PR-4 — это "мозг решений". После того как вакансия получила score, система должна автоматически решить: игнорировать / поставить в очередь / запросить одобрение. Это детерминистическая логика — **никакого LLM**.

## 2.2 Что будет реализовано

```
vacancy.scored event (from worker)
    ↓
Policy Engine читает policy table + today's action count
    ↓
Решение (Founder contract):
  score < 5                          → IGNORE (silent)
  score 5-6, source=hh, limit OK     → AUTO_APPLY
  score 5-6, other src, limit OK     → AUTO_QUEUE
  score 5-6, limit reached           → HOLD (daily summary, not per-vacancy)
  score >= 7                         → APPROVAL_REQUIRED (7 included; limit ignored)
    ↓
Запись в actions table (migration 004: score/reason/actor/correlation_id)
    ↓
Emit vacancy.policy_applied event
    ↓
Telegram notification (per action type; IGNORE+HOLD silent per-vacancy)
```

## 2.3 Архитектурные решения PR-4

### Нет нового ADR — достаточно DECISIONS.md update

Policy engine — чисто детерминистический модуль. Не требует LLM, нет architectural trade-offs. Достаточно записи в DECISIONS.md.

### actions table — расширение схемы

Текущая таблица `actions` минимальна (job_raw_id, action_type, status). Нужно:
- Привязка к score
- reason поле
- actor
- correlation_id

### Policy worker — расширение scoring worker, не отдельный

Два варианта:
1. **Отдельный policy worker** — ещё один asyncio.Task, poll + apply
2. **Inline после scoring** — scoring worker сам вызывает policy engine после save_score

**Решение: вариант 2 (inline).** Потому что:
- Policy evaluation — sync, <1ms, детерминистическая
- Нет смысла в отдельном poll loop для 50 vacancies/day
- Scoring worker уже имеет job_raw_id + score + conn
- Один event flow: scored → policy_applied (не два отдельных цикла)

### Daily limit — counter

Простой COUNT за текущий день:
```sql
SELECT COUNT(*) FROM actions
WHERE action_type IN ('AUTO_QUEUE', 'AUTO_APPLY')
AND date(created_at) = date('now')
```

### Anti-duplicate — company+role check

На PR-4 — упрощённый вариант: canonical_key уже дедуплицирует текст.
Cross-source dedup (company+role) — PR-7 (после normalization).

---

## 2.4 File-by-File Plan

### Commit 1: Docs cleanup + migration

| File | Action | Description |
|------|--------|-------------|
| `core/migrations/004_actions_extend.sql` | CREATE | Extend actions table |
| `docs/CHAT_HANDOFF.md` | MODIFY | Update to reflect current state |
| `docs/TOKEN_BUDGET.md` | MODIFY | Add "LLM for scoring" as approved |
| `BACKLOG.md` | MODIFY | PR-3 DONE, PR-4 IN PROGRESS |

**004_actions_extend.sql:**
```sql
ALTER TABLE actions ADD COLUMN score INTEGER;
ALTER TABLE actions ADD COLUMN reason TEXT;
ALTER TABLE actions ADD COLUMN actor TEXT DEFAULT 'system';
ALTER TABLE actions ADD COLUMN correlation_id TEXT;
```

### Commit 2: Policy engine skill

| File | Action | Description |
|------|--------|-------------|
| `capabilities/career_os/skills/apply_policy/__init__.py` | CREATE | |
| `capabilities/career_os/skills/apply_policy/SKILL.md` | CREATE | Skill contract |
| `capabilities/career_os/skills/apply_policy/engine.py` | CREATE | Policy evaluation logic |
| `capabilities/career_os/skills/apply_policy/store.py` | CREATE | Actions persistence + daily counter |

### Commit 3: Integrate into scoring worker

| File | Action | Description |
|------|--------|-------------|
| `capabilities/career_os/skills/match_scoring/worker.py` | MODIFY | Call policy engine after scoring |

### Commit 4: Tests

| File | Action | Description |
|------|--------|-------------|
| `tests/test_policy_engine.py` | CREATE | Unit tests for policy logic |
| `tests/test_policy_store.py` | CREATE | Actions persistence tests |

### Commit 5: Documentation

| File | Action | Description |
|------|--------|-------------|
| `STATUS.md` | MODIFY | PR-4 done |
| `DECISIONS.md` | MODIFY | Policy engine decisions |
| `CHANGELOG.md` | MODIFY | PR-4 entry |

---

## 2.5 Acceptance Criteria

- [ ] Score < 5 → IGNORE (silent, no notification)
- [ ] Score 5-6, hh, limit OK → AUTO_APPLY, Telegram: "🟡 6/10 — Автоотклик HH"
- [ ] Score 5-6, tg, limit OK → AUTO_QUEUE, Telegram: "🟡 6/10 — В очереди"
- [ ] Score 5-6, limit reached → HOLD (silent per-vacancy; daily summary sent once)
- [ ] Score >= 7 → APPROVAL_REQUIRED, Telegram: "🟢 7/10 — Требует одобрения"
- [ ] actions table содержит записи с правильными action_type + reason
- [ ] events содержит vacancy.policy_applied
- [ ] Тесты покрывают все 4 ветки + edge cases (score=5, score=7, limit boundary)
- [ ] Policy table читается, не hardcoded
- [ ] `pytest` — все новые + существующие тесты зелёные

---

## 2.6 Risks

| Риск | Mitigation |
|------|-----------|
| Daily limit counter timezone | Используем UTC (SQLite date('now') = UTC) |
| Concurrent scoring + policy (race) | Single-threaded asyncio — нет race condition |
| Policy table пуста | init_db seeds default row (уже работает) |
