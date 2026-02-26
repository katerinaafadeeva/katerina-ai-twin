# MVP v1 — PIVOT: Playwright Apply Engine
## Chief Architect Analysis & Complete Documentation Pack

**Date:** 2026-02-24
**Trigger:** HH.ru закрыл applicant API для сторонних приложений (декабрь 2025). OAuth регистрация для соискателей невозможна.
**Decision:** Pivot с API-based apply на browser automation (Playwright).

---

# ═══════════════════════════════════════════
# ЧАСТЬ 1: АНАЛИЗ СИТУАЦИИ
# ═══════════════════════════════════════════

## 1.1 Что произошло

С декабря 2025 HH.ru начал блокировку публичного API для сторонних сервисов автооткликов. Ключевые факты (подтверждено Habr, декабрь 2025):

- HH блокирует IP-адреса сторонних сервисов
- Усиливает защиту (CAPTCHA, rate limiting)
- Регистрация applicant-приложений на dev.hh.ru фактически невозможна для частных лиц
- **Анонимный GET /vacancies (поиск) — пока работает.** Блокировки касаются applicant-действий (отклики, резюме, negotiations)
- Мотивы HH: борьба с массовыми спам-откликами + коммерческая стратегия (свои платные сервисы)

## 1.2 Что это значит для нас

| Компонент | Статус | Действие |
|-----------|--------|----------|
| PR-6: HH ingest (GET /vacancies) | ✅ НЕ ЗАТРОНУТ | Анонимный поиск работает. Реализуем как планировали. |
| PR-7: Cover letter (LLM) | ✅ НЕ ЗАТРОНУТ | Генерация текста — внутренняя операция. |
| PR-8: Auto-apply via API | ❌ ЗАБЛОКИРОВАН | OAuth для applicant невозможен. PIVOT на Playwright. |

## 1.3 Оценка вариантов

| Вариант | Feasibility | Risk | Maintenance | Verdict |
|---------|-------------|------|-------------|---------|
| **A. Playwright (browser automation)** | ВЫСОКАЯ | СРЕДНИЙ (CAPTCHA, UI changes) | СРЕДНИЙ | ✅ **ВЫБИРАЕМ** |
| B. Работодательская схема | НЕТ | Не применима — мы соискатель | — | ❌ |
| C. Reverse engineering / неофиц. API | СРЕДНЯЯ | ОЧЕНЬ ВЫСОКИЙ (бан аккаунта, юр. риски) | ВЫСОКИЙ | ❌ |
| D. Ручной apply (не автоматизируем) | 100% | Нулевой | Нулевой | ❌ (противоречит MVP) |

**Playwright — правильный выбор.** Это то, что делают все выжившие сервисы (Софи и др. по Habr-статье). Для personal single-user tool риски минимальны: ты действуешь как обычный пользователь через браузер, с нормальной скоростью.

---

# ═══════════════════════════════════════════
# ЧАСТЬ 2: CJM REVIEW
# ═══════════════════════════════════════════

Твой CJM-документ проанализирован. **Он хороший.** Общая логика верная, несколько коррекций ниже.

## 2.1 Что в CJM правильно ✅

- Разделение ролей (Telegram=пульт, SQLite=память, Playwright=руки, LLM=мозг) — точная метафора
- Этап 0 (setup + /hh_login) — правильно, именно так Playwright аутентификация работает
- storage_state.json как "сохранённая сессия" — верно, это не пароль
- Pre-filter → Scoring → Policy → Apply цепочка — совпадает с нашей архитектурой
- Лимиты (SCORING_DAILY_CAP, APPLY_DAILY_CAP, COVER_LETTER_DAILY_CAP) — правильный подход
- Обработка ошибок (протухшая сессия, защита HH, LLM cap) — все сценарии покрыты
- Режим A для cover letter (шаблоны в файле) — верно для MVP

## 2.2 Коррекции и уточнения

### Коррекция 1: Ingest остаётся через API, не через Playwright

CJM говорит "агент подтягивает вакансии с HH", но не уточняет как. Уточняем:

```
INGEST (сбор вакансий) = HH REST API (GET /vacancies) — анонимный, без OAuth
APPLY (отклики) = Playwright browser automation — через сохранённую сессию
```

Не нужно парсить HH через Playwright для сбора вакансий. API быстрее, надёжнее, даёт структурированный JSON. Playwright — только для действий, требующих авторизации.

### Коррекция 2: resume_id не нужен в .env

В Playwright-модели мы не указываем resume_id программно. Пользователь логинится → браузер видит все резюме → мы выбираем default resume через UI. Конфигурация:

```
HH_DEFAULT_RESUME_NAME="Product Manager"  # текст в названии резюме для выбора
```

Или проще: если у тебя одно резюме — Playwright выбирает единственное доступное.

### Коррекция 3: Fallback cover letter

CJM предлагает "fallback короткий шаблон без LLM" когда cap достигнут. **Одобряю.** Добавляем в profile/:

```
profile/cover_letter_fallback.txt
```

Простой текст-заглушка (~2 предложения), используется когда:
- LLM cap достигнут
- LLM API недоступен (сеть, ошибки)
- Для вакансий где response_letter_required=true, но тратить LLM-токены нерационально

### Коррекция 4: Уточнение apply flow

CJM описывает шаги верно, добавляю конкретику для Playwright:

```python
async def apply_to_vacancy(page, vacancy_url, cover_letter_text):
    # 1. Navigate
    await page.goto(vacancy_url)
    
    # 2. Check auth (look for apply button vs login prompt)
    if await page.query_selector('[data-qa="login-button"]'):
        raise AuthExpiredError()
    
    # 3. Find apply button
    apply_btn = await page.query_selector('[data-qa="vacancy-response-link-top"]')
    if not apply_btn:
        # Check if already applied
        if await page.query_selector('[data-qa="vacancy-response-link-view-topic"]'):
            return ApplyResult.ALREADY_APPLIED
        # Check if direct/external
        if await page.query_selector('[data-qa="vacancy-response-link-direct"]'):
            return ApplyResult.DIRECT_EXTERNAL
        return ApplyResult.BUTTON_NOT_FOUND
    
    # 4. Click apply
    await apply_btn.click()
    
    # 5. Select resume (if multiple)
    # ... wait for modal, select by name or first available
    
    # 6. Fill cover letter
    letter_field = await page.query_selector('[data-qa="vacancy-response-popup-form-letter-input"]')
    if letter_field:
        await letter_field.fill(cover_letter_text)
    
    # 7. Submit
    submit_btn = await page.query_selector('[data-qa="vacancy-response-submit-popup"]')
    await submit_btn.click()
    
    # 8. Verify success
    # ... wait for confirmation element
    return ApplyResult.SUCCESS
```

### Коррекция 5: CAPTCHA handling

CJM не упоминает CAPTCHA. Добавляем сценарий:

```
Если HH показывает CAPTCHA:
  1. Playwright делает скриншот
  2. Отправляет скриншот в Telegram: "🔒 Требуется CAPTCHA"
  3. Все apply переходят в blocked_captcha
  4. Пользователь решает CAPTCHA вручную (/hh_login или через /hh_captcha)
  5. После решения — apply resume
  
НЕ используем сервисы автоматического решения CAPTCHA.
```

### Коррекция 6: Добавить test/questionnaire detection

```
Если вакансия требует тест/анкету:
  status = MANUAL_REQUIRED
  TG: "🧩 Вакансия {name} требует тест. Откликнитесь вручную: {url}"
```

Playwright НЕ пытается проходить тесты.

## 2.3 Финальный CJM (исправленный)

```
SETUP (однократно):
  pip install → .env config → /hh_login → storage_state.json saved

DAILY LOOP:
  ┌─ HH API (anonymous) ─────── vacancy search ─── job_raw (source="hh")
  │                                                      │
  ├─ TG forward ──────────────── manual forward ─── job_raw (source="telegram")
  │                                                      │
  │                                                      ▼
  │                                              PRE-FILTER (deterministic)
  │                                              negative signals, industries
  │                                                      │
  │                                              SCORING (LLM, capped)
  │                                                      │
  │                                              POLICY (deterministic)
  │                                                      │
  │                         ┌────────────────────────────┼──────────────────┐
  │                         │                            │                  │
  │                    score < 5                    score 5-6          score ≥ 7
  │                    IGNORE                       AUTO_APPLY         APPROVAL_REQ
  │                    (silence)                         │                  │
  │                                                      │            TG: card +
  │                                              cover letter gen    cover letter +
  │                                              (LLM or fallback)   buttons
  │                                                      │                  │
  │                                              PLAYWRIGHT APPLY    WAIT approval
  │                                              (browser auto)           │
  │                                                      │          ┌─────┼──────┐
  │                                              TG: ✅/❌/🧩      Approve Reject Snooze
  │                                                                     │
  │                                                              PLAYWRIGHT APPLY
  └─────────────────────────────────────────────────────────────────────┘

ERROR HANDLING:
  Auth expired → blocked_auth → TG: "/hh_login required"
  CAPTCHA → blocked_captcha → TG: screenshot + manual solve
  Test required → MANUAL_REQUIRED → TG: link
  HH rate limit → backoff → slower pace
  LLM cap → fallback template for cover letters
  Apply cap reached → HOLD → daily summary
```

---

# ═══════════════════════════════════════════
# ЧАСТЬ 3: ОБНОВЛЁННЫЙ ROADMAP
# ═══════════════════════════════════════════

## PR Structure (revised)

| PR | Scope | Time | Deps |
|----|-------|------|------|
| **PR-6** | HH Ingest (API, anonymous) | 3-4h | — |
| **PR-7** | Cover Letter Generation (LLM) | 2-3h | PR-6 |
| **PR-8** | Playwright Apply Engine | 4-6h | PR-7 |
| **PR-9** | Data normalization (job_parsed) | 3-4h | PR-8 |
| **MVP v2** | FSD-lite UI (FastAPI + React) | 2-3 weeks | PR-9 |

### PR-6: HH Ingest — БЕЗ ИЗМЕНЕНИЙ
Существующий TASK_PR6_IMPLEMENTATION.md полностью валиден. Anonymous GET /vacancies не затронут блокировкой. Единственное дополнение: проверить что API реально отвечает перед merge (smoke test curl).

### PR-7: Cover Letter Generation — НЕБОЛЬШИЕ ИЗМЕНЕНИЯ
Добавляется:
- Fallback template (profile/cover_letter_fallback.txt)
- COVER_LETTER_DAILY_CAP config
- Cover letter хранится в DB для последующей вставки через Playwright

### PR-8: Playwright Apply Engine — ПОЛНОСТЬЮ НОВЫЙ
Вместо OAuth + POST /negotiations:
- Playwright + persistent browser context
- /hh_login command (Telegram) → manual login → save storage_state
- Apply queue worker → opens vacancy URL → clicks "Откликнуться" → fills cover letter → submits
- Error handling: auth expired, CAPTCHA, test required, already applied
- Apply audit: hh_applications table + events

### PR-9: Data Normalization
Без изменений от предыдущего плана.

---

# ═══════════════════════════════════════════
# ЧАСТЬ 4: PR-6 — IMPLEMENTATION TASK (ОБНОВЛЁННЫЙ)
# ═══════════════════════════════════════════

**Изменения от предыдущей версии:** Минимальные. Добавлен smoke test API, уточнения по .env. Основной TASK_PR6_IMPLEMENTATION.md остаётся валидным. Ниже — дельта (что добавить/изменить).

### Дополнение к Step 2 (Config):

В .env.example добавить комментарий:

```bash
# === HH.RU SETTINGS ===
# Ingest uses anonymous API (no OAuth needed)
# Apply will use Playwright (PR-8)
HH_ENABLED=false
HH_POLL_INTERVAL=3600
HH_USER_AGENT=KaterinaAITwin/0.1 (contact@example.com)
HH_MAX_PAGES=5
HH_SCORING_DAILY_CAP=100
HH_SEARCHES_PATH=identity/hh_searches.json
# NOTE: No HH_CLIENT_ID/SECRET needed. Applicant API is discontinued.
# Auto-apply uses Playwright browser automation (PR-8).
```

### Дополнение к Step 9 (Documentation):

В DECISIONS.md добавить запись:

```markdown
## 2026-02-24: HH Applicant API Discontinued — Playwright Pivot

HH.ru закрыл публичный API для applicant-действий (отклики, резюме) в декабре 2025.
Регистрация приложений для соискателей невозможна.

**Решение:** 
- Ingest (поиск вакансий) = anonymous HH API (GET /vacancies) — работает
- Apply (отклики) = Playwright browser automation с сохранённой сессией
- OAuth НЕ используется. CLIENT_ID/SECRET не нужны.

**Обоснование:**
- Playwright имитирует действия обычного пользователя через браузер
- Сессия сохраняется локально (storage_state.json)
- Пароль HH нигде не хранится в системе
- Скорость apply ограничена лимитами (не больше обычного пользователя)
```

### Шаги для Катерины ПЕРЕД мержем PR-6:

1. **Проверь что API отвечает:**
```bash
curl -H 'User-Agent: KaterinaAITwin/0.1' 'https://api.hh.ru/vacancies?text=Product+Manager&area=1&per_page=3'
```
Должен вернуть JSON с вакансиями. Если 403/429 — API тоже заблокирован, нужен pivot на Playwright для ingest тоже.

2. **Создай identity/hh_searches.json** (из примера):
```json
[
  {"text": "Product Manager", "area": "1", "schedule": "remote"},
  {"text": "Product Owner", "area": "113"}
]
```

3. **Запусти тесты:** `pytest` — все 130+ existing + ~30 new должны быть зелёные.

4. **Проверь git status:** никаких секретов, hh_searches.json в .gitignore, identity/ не коммитится.

5. **Smoke test:** запусти бота, подожди один poll cycle, проверь что вакансии появились в job_raw.

---

# ═══════════════════════════════════════════
# ЧАСТЬ 5: БЕЗОПАСНОСТЬ (PLAYWRIGHT MODEL)
# ═══════════════════════════════════════════

## 5.1 Что хранится

| Файл | Содержимое | Где | Gitignored |
|------|-----------|-----|------------|
| .env | Bot token, Anthropic key, HH config | project root | ✅ |
| data/hh_storage_state.json | Browser session (cookies, localStorage) | data/ | ✅ |
| identity/hh_searches.json | Search queries | identity/ | ✅ |
| profile/cover_letter_templates.md | Letter templates | profile/ | ✅ |
| profile/cover_letter_fallback.txt | Fallback letter | profile/ | ✅ |

## 5.2 Что НЕ хранится (никогда)

- ❌ Логин/пароль HH
- ❌ OAuth tokens (не используются)
- ❌ Cookies в логах
- ❌ Storage state в git
- ❌ Персональные данные в events

## 5.3 Session lifecycle

```
/hh_login (Telegram command)
    → Playwright opens Chromium (headful mode)
    → User manually logs into hh.ru
    → User completes 2FA if needed
    → Playwright saves: data/hh_storage_state.json
    → Chromium closes
    → Bot confirms: "✅ Сессия HH сохранена"

Apply worker:
    → Playwright opens Chromium (headless mode)
    → Loads storage_state.json → already authenticated
    → Performs apply actions
    → If 401/login screen → stops, asks for /hh_login

Session expiry:
    → HH sessions typically last 2-4 weeks
    → When expired → TG notification → /hh_login
    → All pending applies → blocked_auth status
```

## 5.4 Anti-detection (important!)

Чтобы HH не заблокировал как бота:

1. **Human-like timing:** Random delay 3-8 sec between actions
2. **Realistic user agent:** Standard Chrome UA (Playwright default)
3. **No parallel tabs:** One action at a time
4. **Rate limit:** Max 10-15 applies/hour (human pace)
5. **Playwright stealth:** Use `playwright-stealth` plugin (patches navigator.webdriver flag)
6. **Daily limit:** 20-40 applies/day max (configurable via APPLY_DAILY_CAP)
7. **No headless detection bypass attempts** — just act like a slow, careful human

## 5.5 Threat model (updated)

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| HH bans account for automation | HIGH | Human-like timing, low rate, stealth plugin |
| Session file stolen | MEDIUM | Local only, gitignored, no cloud sync |
| CAPTCHA blocks apply | MEDIUM | Screenshot to TG, manual solve, no auto-CAPTCHA |
| HH changes UI selectors | MEDIUM | Playwright selectors in config, easy to update |
| IP blocking | LOW | Single user, residential IP, normal volume |
| Storage state corruption | LOW | /hh_login recreates from scratch |

---

# ═══════════════════════════════════════════
# ЧАСТЬ 6: PR-7 & PR-8 PREVIEW
# ═══════════════════════════════════════════

## PR-7: Cover Letter Generation

**New files:**
```
capabilities/career_os/skills/cover_letter/
├── __init__.py
├── SKILL.md
├── generator.py          # LLM cover letter generation
├── store.py              # Save/retrieve from DB
└── fallback.py           # Fallback template logic
profile/
├── cover_letter_templates.md   # LLM prompt templates (gitignored)
└── cover_letter_fallback.txt   # Static fallback (gitignored)
core/migrations/007_cover_letters.sql
```

**Migration 007:**
```sql
CREATE TABLE IF NOT EXISTS cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_raw_id INTEGER NOT NULL REFERENCES job_raw(id),
    text TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    is_fallback BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cover_letters_job ON cover_letters(job_raw_id);
```

**Config additions:**
```
COVER_LETTER_DAILY_CAP=50
COVER_LETTER_MODEL=claude-haiku
```

## PR-8: Playwright Apply Engine

**New files:**
```
connectors/hh_browser.py           # Playwright browser management
capabilities/career_os/skills/hh_apply/
├── __init__.py
├── SKILL.md
├── applier.py             # Apply logic (navigate, fill, submit)
├── auth.py                # Login flow, session management
├── selectors.py           # HH.ru CSS/data-qa selectors (easy to update)
├── worker.py              # Apply queue worker
└── captcha_handler.py     # CAPTCHA detection + TG notification
core/migrations/008_hh_applications.sql
data/                      # storage_state.json lives here (gitignored)
```

**Migration 008:**
```sql
CREATE TABLE IF NOT EXISTS hh_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_raw_id INTEGER NOT NULL REFERENCES job_raw(id),
    hh_vacancy_id TEXT NOT NULL,
    cover_letter_id INTEGER REFERENCES cover_letters(id),
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/applied/failed/manual_required/blocked_auth/blocked_captcha
    error_message TEXT,
    screenshot_path TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hh_app_status ON hh_applications(status);
CREATE INDEX IF NOT EXISTS idx_hh_app_vacancy ON hh_applications(hh_vacancy_id);
```

**New dependency:** `playwright` (pip install playwright && playwright install chromium)

**Key design: selectors.py**
```python
# Centralized HH.ru selectors — when HH changes UI, update only this file
SELECTORS = {
    "apply_button": '[data-qa="vacancy-response-link-top"]',
    "already_applied": '[data-qa="vacancy-response-link-view-topic"]',
    "direct_link": '[data-qa="vacancy-response-link-direct"]',
    "letter_input": '[data-qa="vacancy-response-popup-form-letter-input"]',
    "submit_button": '[data-qa="vacancy-response-submit-popup"]',
    "login_button": '[data-qa="login-button"]',
    "resume_select": '[data-qa="resume-select"]',
    "success_message": '[data-qa="vacancy-response-link-view-topic"]',
}
```

Selectors in separate file = если HH изменит UI, правишь одн файл, не трогая логику.

**Config additions:**
```
APPLY_DAILY_CAP=20
APPLY_MIN_DELAY=3          # seconds between actions
APPLY_MAX_DELAY=8          # random delay range
HH_STORAGE_STATE_PATH=data/hh_storage_state.json
PLAYWRIGHT_HEADLESS=true   # false for /hh_login
```

---

# ═══════════════════════════════════════════
# ЧАСТЬ 7: TOKEN ECONOMY (FINAL, с Playwright)
# ═══════════════════════════════════════════

| Operation | Volume/day | Cost/day | Notes |
|-----------|-----------|----------|-------|
| HH API search (ingest) | ~3-5 requests | $0 | Anonymous, free |
| LLM scoring | ~100-150 | ~$0.08-0.12 | Haiku, capped |
| LLM cover letters | ~30-50 | ~$0.06-0.10 | Haiku, capped |
| Playwright browser | ~20-40 applies | ~$0 | Local compute only |
| Fallback letters | ~5-10 | $0 | Static template, no LLM |
| **Total** | | **~$0.14-0.22/day** | **~$4-7/month** |

Playwright не добавляет денежных затрат — это локальный браузер. Добавляет ~200MB RAM и немного CPU.

---

# ═══════════════════════════════════════════
# ЧАСТЬ 8: ДОКУМЕНТЫ ДЛЯ РЕПОЗИТОРИЯ
# ═══════════════════════════════════════════

Ниже — документы, которые нужно добавить/обновить в репозитории, чтобы агент (Claude Code / Tech Lead) ориентировался в новой архитектуре.

## 8.1 ARCHITECTURE.md (новый файл, корень репо)

```markdown
# AI Twin — Architecture Overview

## System Components

### Data Flow
```
HH.ru API (anonymous) ──→ HH Ingest Worker ──→ job_raw (SQLite)
Telegram forwards ──────→ TG Ingest Handler ──→ job_raw (SQLite)
                                                       │
                                               Pre-filter (deterministic)
                                                       │
                                               Scoring Worker (LLM)
                                                       │
                                               Policy Engine (deterministic)
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    │                  │                  │
                               IGNORE            AUTO_APPLY         APPROVAL_REQ
                                                     │                   │
                                              Cover Letter Gen     Cover Letter Gen
                                              (LLM/fallback)      (LLM/fallback)
                                                     │                   │
                                              Playwright Apply     TG Notification
                                              (browser auto)      (approve/reject)
                                                     │                   │
                                              TG Notification     On Approve →
                                              (result)            Playwright Apply
```

### Key Design Decisions
- **Ingest:** HH REST API (anonymous, no OAuth) for vacancy search
- **Apply:** Playwright browser automation (HH applicant API discontinued Dec 2025)
- **Scoring:** LLM (Haiku) with deterministic pre-filter to reduce costs
- **Policy:** Fully deterministic, no LLM involvement
- **Cover Letters:** LLM with static fallback template
- **Auth:** Browser session (storage_state.json), manual login via /hh_login

### Security Model
- No HH credentials stored anywhere (login is manual in browser)
- Browser session saved locally (data/hh_storage_state.json, gitignored)
- No OAuth tokens (applicant API discontinued)
- Human-like apply timing (3-8s delays, 20-40/day max)
```

## 8.2 Обновление DECISIONS.md

Добавить запись (см. Часть 4, Step 9 дополнение).

## 8.3 Обновление STATUS.md

```markdown
## Current: PR-6 (HH Ingest)
- Branch: pr6-hh-ingest
- Status: IN PROGRESS

## Architecture Pivot (2026-02-24)
- HH applicant API discontinued (Dec 2025)
- Apply mechanism: Playwright browser automation (not API)
- Ingest: unchanged (anonymous API)
- No OAuth integration needed
```

## 8.4 Обновление BACKLOG.md

```markdown
## MVP v1.1 (Today)
- [x] PR-5: Telegram Approval UX ✅ MERGED
- [ ] PR-6: HH Ingest (anonymous API) ← CURRENT
- [ ] PR-7: Cover Letter Generation (LLM + fallback)

## MVP v1.2 (Tomorrow)
- [ ] PR-8: Playwright Apply Engine (browser automation)

## MVP v1 COMPLETE when:
HH search → score → cover letter → auto-apply via browser → TG notification

## Post-MVP v1
- [ ] PR-9: Data normalization (job_parsed)
- [ ] MVP v2: FSD-lite UI (FastAPI + React)
```

---

# ═══════════════════════════════════════════
# ЧАСТЬ 9: CHECKLIST — ПЕРЕД MERGE PR-6
# ═══════════════════════════════════════════

Katerina, вот точный checklist для тебя перед мержем PR-6:

### Перед началом реализации:
- [ ] Проверь что HH API отвечает (curl команда из Части 4)
- [ ] Создай файл `identity/hh_searches.json` с твоими поисковыми запросами
- [ ] Убедись что ветка `pr6-hh-ingest` создана от актуального `main`

### После реализации (Tech Lead завершил 9 шагов):
- [ ] `pytest` — все тесты зелёные (130 existing + ~30 new = ~160)
- [ ] `git diff --name-only main` — только ожидаемые файлы изменены
- [ ] Проверь: никаких секретов в коде (`grep -r "password\|secret\|token" --include="*.py" | grep -v ".env"`)
- [ ] Проверь: `identity/hh_searches.json` в `.gitignore`
- [ ] Проверь: `.env.example` НЕ содержит CLIENT_ID/SECRET (они не нужны)
- [ ] Проверь: DECISIONS.md содержит запись о Playwright pivot
- [ ] Smoke test: запусти бота → подожди poll cycle → проверь job_raw в БД
- [ ] QA Gate: прогони QA_GATE_PR6.md (уже создан)
- [ ] Вернись сюда на Chief Architect review

---

# ═══════════════════════════════════════════
# ЧАСТЬ 10: ЭКОНОМИЯ РЕСУРСОВ
# ═══════════════════════════════════════════

## Что мы экономим с Playwright vs OAuth:

1. **Нет OAuth complexity:** Не нужен token refresh, token storage encryption, registration на dev.hh.ru
2. **Нет зависимости от API policy:** HH может менять API rules, но браузер работает пока работает сайт
3. **Playwright reusable:** Тот же механизм для любой job-платформы (SuperJob, LinkedIn, Работа.ру)

## Что стоит дороже:

1. **Maintenance:** HH может менять UI → нужно обновлять selectors.py
2. **Reliability:** Браузер может падать, сессия протухать
3. **Speed:** Playwright медленнее API (~5 sec per apply vs ~0.5 sec)

## Mitigation:

- Selectors в отдельном файле — обновление за 5 минут
- Retry logic с exponential backoff
- Session auto-check перед каждой серией applies
- Screenshot на каждую ошибку для быстрой диагностики
