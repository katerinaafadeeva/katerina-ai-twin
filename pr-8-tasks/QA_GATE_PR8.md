# QA / SECURITY GATE — PR-8: Playwright Auto-Apply

**Дата:** 2026-02-25
**Роль:** QA-ревьюер. Проверяй критично. Сообщай только о проблемах.
**Модель:** Sonnet (в Claude Code)

---

## GATE 1: После Step 4 (Store + Browser connector)

### 1.1 Регрессия

```bash
python3 -m pytest -q
# ВСЕ существующие ~225 тестов зелёные
```

```bash
git diff main -- capabilities/career_os/skills/apply_policy/engine.py | wc -l
# Ожидание: 0 (engine.py не тронут)

git diff main -- capabilities/career_os/skills/match_scoring/handler.py | wc -l
# Ожидание: 0 (handler.py не тронут)

git diff main -- capabilities/career_os/skills/cover_letter/generator.py | wc -l
# Ожидание: 0 (generator.py не тронут)
```

### 1.2 Миграция 008

```bash
python -c "from core.db import init_db; init_db(); print('OK')"
```

- [ ] execution_status column exists on actions
- [ ] execution_error column exists
- [ ] execution_attempts column exists (DEFAULT 0)
- [ ] applied_at column exists
- [ ] hh_vacancy_id column exists
- [ ] Index idx_actions_execution created

### 1.3 Config

```bash
python -c "
from core.config import config
print('Apply enabled:', config.hh_apply_enabled)
print('Cap:', config.apply_daily_cap)
print('Delay:', config.apply_delay_min, '-', config.apply_delay_max)
print('Batch:', config.apply_batch_size)
print('Storage:', config.hh_storage_state_path)
"
```

- [ ] hh_apply_enabled defaults to False
- [ ] apply_daily_cap defaults to 20
- [ ] All config fields read correctly from env

### 1.4 Selectors

- [ ] `connectors/hh_browser/selectors.py` exists
- [ ] Uses data-qa attributes (not CSS classes where possible)
- [ ] CAPTCHA_KEYWORDS includes Russian terms

### 1.5 Browser client

- [ ] `client.py`: HHBrowserClient is singleton-like
- [ ] Checks storage_state_path exists before start
- [ ] Saves storage_state on stop
- [ ] No hardcoded credentials

### 1.6 Apply flow

- [ ] `apply_flow.py`: handles all outcomes (applied, already_applied, has_test, external, captcha, session_expired, timeout, unexpected)
- [ ] Navigation timeout reasonable (15 sec)
- [ ] Try/except wraps entire flow (never crashes)
- [ ] Returns ApplyResult (not raises exceptions)

### 1.7 Store

- [ ] `get_pending_apply_tasks`: only source='hh', only NULL execution_status
- [ ] Two query paths: AUTO_APPLY created + APPROVAL_REQUIRED approved
- [ ] Max 3 days old filter
- [ ] `update_execution_status`: sets applied_at only for 'applied'
- [ ] `get_today_apply_count`: counts only 'applied' + today
- [ ] `extract_hh_vacancy_id`: handles URL and source_id

### 1.8 Security

- [ ] identity/hh_storage_state.json already in .gitignore
- [ ] No cookies/headers/tokens in logs
- [ ] No hardcoded URLs with auth tokens
- [ ] Bootstrap saves to gitignored path

---

## GATE 2: После Step 9 (Final — all steps complete)

### 2.1 Полная регрессия

```bash
python3 -m pytest -q
# ~255 тестов total, ВСЕ зелёные
```

```bash
# Policy engine не тронут
git diff main -- capabilities/career_os/skills/apply_policy/engine.py | wc -l
# 0

# Scoring handler не тронут
git diff main -- capabilities/career_os/skills/match_scoring/handler.py | wc -l
# 0

# Cover letter generator не тронут
git diff main -- capabilities/career_os/skills/cover_letter/generator.py | wc -l
# 0
```

### 2.2 Worker интеграция

- [ ] Apply worker starts ONLY when HH_APPLY_ENABLED=true
- [ ] Apply worker registered as asyncio.Task in telegram_bot.py
- [ ] HH_APPLY_ENABLED=false → worker NOT started → no Playwright import errors
- [ ] Worker handles browser start failure gracefully
- [ ] Worker handles empty queue (no crash, just debug log)

### 2.3 Daily cap

- [ ] `get_today_apply_count` works correctly
- [ ] Cap check happens BEFORE getting tasks
- [ ] Cap reached → emit hh.apply_cap_reached event
- [ ] Cap reached → NO browser launched

### 2.4 Anti-ban

- [ ] Random delay between applies (APPLY_DELAY_MIN..APPLY_DELAY_MAX)
- [ ] Batch size limited (APPLY_BATCH_SIZE)
- [ ] Realistic User-Agent
- [ ] Viewport 1280x800
- [ ] Locale ru-RU

### 2.5 CAPTCHA handling

- [ ] Captcha detected → stop entire batch (not just current vacancy)
- [ ] Captcha → emit hh.apply_captcha event
- [ ] Captcha → TG notification with /resume_apply instruction
- [ ] /resume_apply command registered and works

### 2.6 Session management

- [ ] Session expired → emit hh.session_expired event
- [ ] Session expired → TG notification
- [ ] Bootstrap script works (`python -m connectors.hh_browser.bootstrap`)

### 2.7 Manual required cases

- [ ] has_test → manual_required + TG notification with vacancy link
- [ ] external_link → manual_required + TG notification
- [ ] Already applied → treated as success (idempotent)

### 2.8 Events (audit trail)

```sql
-- Check all events are emitted correctly
SELECT DISTINCT event_name FROM events WHERE event_name LIKE 'hh.apply%';
```

- [ ] hh.apply_started
- [ ] hh.apply_succeeded
- [ ] hh.apply_failed
- [ ] hh.apply_manual_required
- [ ] hh.apply_captcha
- [ ] hh.apply_cap_reached
- [ ] hh.session_expired

### 2.9 Тесты PR-8

- [ ] `test_hh_apply_store.py`: pending tasks, execution status, daily count, extract ID
- [ ] `test_hh_apply_worker.py`: success, manual, captcha stops, cap, delay (ALL mocked)
- [ ] `test_hh_apply_flow.py`: all outcomes mocked (success, test, external, captcha, expired, timeout)
- [ ] NO real Playwright in tests
- [ ] NO real HH.ru calls in tests

### 2.10 Документация

- [ ] STATUS.md: PR-8 ✅ DONE, MVP v1 ✅ COMPLETE
- [ ] CHANGELOG.md: PR-8 section with Added/Changed/Events
- [ ] DECISIONS.md: PR-8 decisions (execution_status, singleton browser, feature flag, captcha, retry)
- [ ] BACKLOG.md: PR-8 DONE
- [ ] SKILL.md in hh_apply/
- [ ] .env.example updated with all HH_APPLY_* vars

### 2.11 Zero LLM calls

- [ ] `git diff main | grep -i "anthropic\|claude\|haiku\|sonnet" | grep -v "#\|comment\|test\|doc"` → NO new LLM calls
- [ ] No new imports of core/llm in PR-8 code

---

## 3. Блокеры merge

**БЛОКИРУЕТ:**
- ❌ Любой существующий тест падает
- ❌ engine.py / handler.py / generator.py изменены
- ❌ Worker запускается при HH_APPLY_ENABLED=false
- ❌ Credentials/cookies/PII в логах
- ❌ No try/except around browser operations in worker
- ❌ Tests call real HH.ru

**НЕ блокирует:**
- ⚠️ Smoke test не проведён (нужна реальная сессия HH)
- ⚠️ Selectors не верифицированы на актуальной странице HH
- ⚠️ Docker support (post-MVP)

---

## 4. Формат QA отчёта (на русском)

```
## QA-отчёт PR-8

### Статус: ✅ PASS / ❌ FAIL

### Тесты
- Всего: N | Новых: N | Упавших: 0

### Регрессия
- engine.py: не тронут ✅/❌
- handler.py: не тронут ✅/❌
- generator.py: не тронут ✅/❌
- worker.py (scoring): изолировано ✅/❌

### Новая функциональность
- Migration 008: ✅/❌
- Browser client: ✅/❌
- Apply flow: ✅/❌
- Store: ✅/❌
- Worker: ✅/❌
- Notifier: ✅/❌

### Security
- Feature flag: ✅/❌
- No credentials in logs: ✅/❌
- storage_state gitignored: ✅/❌
- Zero LLM calls: ✅/❌

### Anti-ban
- Random delays: ✅/❌
- Daily cap: ✅/❌
- Batch size limit: ✅/❌

### Документация
- STATUS/CHANGELOG/DECISIONS/BACKLOG: ✅/❌

### Блокеры
- (список)

### Рекомендация
✅ Готово к merge / ❌ Требует доработки
```
