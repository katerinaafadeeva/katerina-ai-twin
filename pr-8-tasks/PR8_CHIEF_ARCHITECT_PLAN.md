# PR-8 Chief Architect Plan — Playwright Auto-Apply

**Author:** Chief Architect (Claude Opus)
**Date:** 2026-02-25
**Status:** Ready for implementation
**Scope:** Execution layer — apply decision via browser automation on HH.ru

---

## 1. Позиционирование PR-8

PR-8 — это **execution layer**. Вся интеллектуальная работа уже сделана:
- PR-3: Scoring (LLM Haiku, 0-10)
- PR-4: Policy routing (IGNORED/AUTO_APPLY/HOLD/APPROVAL_REQUIRED)
- PR-7: Cover letter generation (LLM + fallback)

PR-8 берёт готовое решение (action + cover letter) и **физически нажимает "Откликнуться"** на HH.ru через Playwright. Никаких LLM вызовов.

```
                    PR-1..PR-7 (уже есть)
                    ┌──────────────────────┐
HH vacancy ─────►  │ Ingest → Score →     │
                    │ Policy → Cover Letter │
                    └──────────┬───────────┘
                               │
                    PR-8 (этот PR)
                    ┌──────────▼───────────┐
                    │  Playwright executor  │
                    │  - Взять задачу из DB │
                    │  - Открыть HH страницу│
                    │  - Нажать "Откликнуться"│
                    │  - Вставить CL        │
                    │  - Записать результат │
                    └──────────────────────┘
```

---

## 2. Архитектурные решения

### Решение 1: Где хранить результат apply — actions.status (не отдельная таблица)

**Решение:** Расширяем `actions.status` новыми значениями. Отдельную таблицу `apply_runs` НЕ создаём.

**Обоснование для MVP:**
- actions уже содержит action_type (AUTO_APPLY, APPROVAL_REQUIRED) и status (created, approved, rejected, snoozed)
- Добавляем execution-статусы: `applying`, `applied`, `failed`, `manual_required`
- Одна таблица = один запрос для полной картины
- Отдельная таблица apply_runs — over-engineering для 20 откликов/день

**Status transitions:**
```
AUTO_APPLY flow:
  created → applying → applied ✅
                     → failed ❌ (retry possible)
                     → manual_required ⚠️ (тест/анкета/captcha/external)

APPROVAL_REQUIRED flow:
  created → approved → applying → applied ✅
                                → failed ❌
                                → manual_required ⚠️
  created → rejected (не применяем)
  created → snoozed (не применяем)
```

**Миграция:**
```sql
-- 008_apply_execution.sql
ALTER TABLE actions ADD COLUMN execution_status TEXT;
-- NULL = не применяли, 'applying', 'applied', 'failed', 'manual_required'
ALTER TABLE actions ADD COLUMN execution_error TEXT;
-- Причина ошибки: 'has_test', 'external_link', 'captcha', 'network_error', etc.
ALTER TABLE actions ADD COLUMN execution_attempts INTEGER DEFAULT 0;
ALTER TABLE actions ADD COLUMN applied_at TIMESTAMP;
ALTER TABLE actions ADD COLUMN hh_vacancy_id TEXT;
-- Extracted from job_raw for direct URL construction
```

**Почему execution_status отдельно от status:**
- `status` = бизнес-решение (created/approved/rejected/snoozed)
- `execution_status` = техническое исполнение (applying/applied/failed/manual_required)
- Это разные concerns. Approved + failed = "одобрили, но не удалось откликнуться"

### Решение 2: Очередь задач — SQL-based queue

**Решение:** Простой SQL-запрос выбирает задачи к apply.

```sql
-- Задачи к автоматическому apply
SELECT a.id, a.job_raw_id, jr.raw_text, cl.letter_text
FROM actions a
JOIN job_raw jr ON jr.id = a.job_raw_id
LEFT JOIN cover_letters cl ON cl.job_raw_id = a.job_raw_id
WHERE a.action_type = 'AUTO_APPLY'
  AND a.status = 'created'
  AND a.execution_status IS NULL
  AND jr.source = 'hh'
  AND date(a.created_at) >= date('now', '-3 days')  -- не старше 3 дней
ORDER BY a.created_at ASC
LIMIT 5  -- batch size

UNION ALL

-- Одобренные задачи
SELECT a.id, a.job_raw_id, jr.raw_text, cl.letter_text
FROM actions a
JOIN job_raw jr ON jr.id = a.job_raw_id
LEFT JOIN cover_letters cl ON cl.job_raw_id = a.job_raw_id
WHERE a.action_type = 'APPROVAL_REQUIRED'
  AND a.status = 'approved'
  AND a.execution_status IS NULL
  AND jr.source = 'hh'
ORDER BY a.created_at ASC
LIMIT 5
```

**Дедупликация:** Уже обеспечена UNIQUE(job_raw_id, action_type) в actions + execution_status IS NULL фильтр.

**Повторные попытки:** При `failed` + `execution_attempts < MAX_RETRIES(3)` — можно retry. Но для MVP: retry ТОЛЬКО по команде оператора `/retry_apply <action_id>`.

**Backoff:** Не нужен для MVP при 20 откликов/день. Достаточно human-like delays между apply.

### Решение 3: Browser instance — Persistent Context (singleton)

**Решение:** Один persistent browser context, переиспользуемый между apply.

```python
# connectors/hh_browser/client.py

class HHBrowserClient:
    """Singleton Playwright browser for HH.ru automation."""

    def __init__(self, storage_state_path: str):
        self._storage_state_path = storage_state_path
        self._playwright = None
        self._browser = None
        self._context = None

    async def start(self):
        """Launch browser with saved session."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            storage_state=self._storage_state_path,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 ... (realistic UA)",
            locale="ru-RU",
        )

    async def stop(self):
        """Save session and close."""
        if self._context:
            await self._context.storage_state(path=self._storage_state_path)
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def apply_to_vacancy(self, vacancy_url: str, cover_letter: str) -> ApplyResult:
        """Navigate to vacancy and attempt apply."""
        ...
```

**Обоснование:**
- Persistent context = одна авторизация, переиспользуется
- storage_state.json сохраняется после каждого apply (на случай обновления cookies)
- Headless = не требует GUI
- Singleton = один browser instance на весь worker cycle

### Решение 4: Детекция success / test / external / captcha

**Стратегия: Page-based detection после клика "Откликнуться".**

```
Шаг 1: Открыть vacancy_url (https://hh.ru/vacancy/{id})
  → Проверить: страница загрузилась? (timeout → failed, network_error)

Шаг 2: Предварительные проверки
  → has_test badge? (селектор: "[data-qa='vacancy-response-link-test']" или текст "Тестовое задание")
    → Да: manual_required, reason='has_test'
  → Тип отклика "через внешнюю ссылку"? (селектор: кнопка ведёт на external URL)
    → Да: manual_required, reason='external_link'
  → Уже откликались? (селектор: "Вы уже откликнулись" или disabled button)
    → Да: applied (идемпотентность), reason='already_applied'

Шаг 3: Нажать "Откликнуться"
  → Селектор: "[data-qa='vacancy-response-link-top']" или аналог
  → Ожидание: появление формы отклика или redirect

Шаг 4: Вставить cover letter (если форма содержит textarea)
  → Селектор: textarea для сопроводительного
  → Вставить текст из cover_letters table

Шаг 5: Подтвердить отклик
  → Кнопка "Отправить" / "Откликнуться"
  → Ожидание: success indicator

Шаг 6: Проверка результата
  → Success page / confirmation text → applied ✅
  → CAPTCHA / challenge → manual_required, reason='captcha'
  → Error page → failed, reason=<error_text>
```

**Важно о селекторах:** HH.ru периодически меняет вёрстку. Поэтому:
- Селекторы вынесены в отдельный конфиг `connectors/hh_browser/selectors.py`
- Используем `data-qa` атрибуты (более стабильные чем CSS классы)
- При неизвестной разметке → failed, reason='unknown_page_structure'

### Решение 5: UX в Telegram для ручных кейсов

**MVP-минимум:**

```
MANUAL_REQUIRED notification:
┌─────────────────────────────────────┐
│ ⚠️ Требуется ручной отклик          │
│                                     │
│ 📋 Senior PM @ Yandex (7/10)       │
│ 🔗 https://hh.ru/vacancy/123456    │
│ ❌ Причина: тестовое задание        │
│                                     │
│ Откликнитесь вручную на HH.ru     │
└─────────────────────────────────────┘

CAPTCHA notification:
┌─────────────────────────────────────┐
│ 🛑 Captcha на HH.ru                │
│                                     │
│ Автоматические отклики приостановлены│
│ Зайдите на HH.ru, решите капчу,   │
│ затем отправьте /resume_apply      │
└─────────────────────────────────────┘

APPLY SUCCESS (batch summary):
┌─────────────────────────────────────┐
│ ✅ Автоотклики: 5 из 7              │
│                                     │
│ ✅ PM @ Sber (6/10)                 │
│ ✅ Product Lead @ VK (5/10)         │
│ ⚠️ Analyst @ Yandex — тест         │
│ ❌ PM @ Ozon — ошибка              │
│                                     │
│ 📊 Сегодня: 12/20 лимит            │
└─────────────────────────────────────┘
```

**Для captcha в MVP:** нет кнопки "я решил". Только `/resume_apply` команда.
**Обоснование:** Кнопка с callback_data требует persistent state + polling — over-engineering для MVP.

### Решение 6: Rate limiting / Anti-ban

```
APPLY_DAILY_CAP = 20 (env variable, default)
APPLY_DELAY_MIN = 30 (секунд между откликами)
APPLY_DELAY_MAX = 90 (рандомный delay в диапазоне)
APPLY_BATCH_SIZE = 5 (откликов за один цикл worker)
APPLY_WORKER_INTERVAL = 300 (секунд между циклами, default 5 min)
```

**Human-like behavior:**
- Random delay 30-90 сек между откликами
- Random mouse movements перед кликом (опционально, не в MVP)
- Realistic User-Agent
- Viewport 1280x800 (не мобильный)
- Locale ru-RU
- Ограничение batch size: 5 за цикл, пауза 5 мин, следующий цикл

**Daily cap:**
```python
def get_today_apply_count(conn) -> int:
    """Count successful applies today."""
    row = conn.execute("""
        SELECT COUNT(*) FROM actions
        WHERE execution_status = 'applied'
        AND date(applied_at) = date('now')
    """).fetchone()
    return row[0]
```

### Решение 7: Token economy — НОЛЬ новых LLM вызовов

PR-8 НЕ добавляет LLM вызовы. Это чистый execution:
- Scoring: уже есть (PR-3)
- Cover letter: уже есть (PR-7)
- Policy: детерминистический (PR-4)
- Playwright: browser actions, не AI

**Стоимость PR-8:** ~$0/month в LLM costs. Только Playwright overhead (negligible).

---

## 3. Структура файлов

```
connectors/
  hh_browser/
    __init__.py
    client.py          # HHBrowserClient — singleton Playwright wrapper
    selectors.py       # CSS/data-qa selectors, вынесены для поддержки
    apply_flow.py      # Step-by-step apply logic (detect, click, verify)
    bootstrap.py       # Login bootstrap: interactive login → save storage_state

capabilities/career_os/skills/
  hh_apply/
    __init__.py
    SKILL.md           # Skill contract
    store.py           # SQL queries: get pending, update status, daily cap
    worker.py          # Async worker: pick tasks, call browser, update DB
    notifier.py        # Telegram notifications for apply results
```

**Новые config fields:**
```
HH_APPLY_ENABLED=false          # Feature flag (default OFF)
APPLY_DAILY_CAP=20              # Max applies per day
APPLY_DELAY_MIN=30              # Min delay between applies (seconds)
APPLY_DELAY_MAX=90              # Max delay between applies (seconds)
APPLY_BATCH_SIZE=5              # Applies per worker cycle
APPLY_WORKER_INTERVAL=300       # Worker cycle interval (seconds)
HH_STORAGE_STATE_PATH=identity/hh_storage_state.json
```

---

## 4. Bootstrap Login — Prereq от Кати

Перед первым запуском PR-8 нужна одноразовая авторизация:

```bash
python -m connectors.hh_browser.bootstrap
```

Это:
1. Запускает Playwright в HEADED (не headless) режиме
2. Открывает hh.ru/account/login
3. Катерина вводит логин/пароль/2FA вручную
4. После успешного входа → storage_state сохраняется в `identity/hh_storage_state.json`
5. Дальнейшие запуски используют этот файл (headless)

**Когда нужен повтор:** когда сессия истекла (обычно 1-2 недели). Worker детектит и шлёт TG: "Сессия HH истекла, запустите bootstrap".

---

## 5. Миграция 008

```sql
-- core/migrations/008_apply_execution.sql

ALTER TABLE actions ADD COLUMN execution_status TEXT;
ALTER TABLE actions ADD COLUMN execution_error TEXT;
ALTER TABLE actions ADD COLUMN execution_attempts INTEGER DEFAULT 0;
ALTER TABLE actions ADD COLUMN applied_at TIMESTAMP;
ALTER TABLE actions ADD COLUMN hh_vacancy_id TEXT;

CREATE INDEX IF NOT EXISTS idx_actions_execution
ON actions(execution_status, action_type);
```

---

## 6. Events (audit trail)

| Event | Actor | Payload | Когда |
|-------|-------|---------|-------|
| `hh.apply_started` | `hh_apply_worker` | action_id, vacancy_url | Начало apply |
| `hh.apply_succeeded` | `hh_apply_worker` | action_id, vacancy_url | Успех |
| `hh.apply_failed` | `hh_apply_worker` | action_id, error, attempts | Ошибка |
| `hh.apply_manual_required` | `hh_apply_worker` | action_id, reason | Тест/анкета/captcha/external |
| `hh.apply_captcha` | `hh_apply_worker` | action_id | Captcha обнаружена |
| `hh.apply_cap_reached` | `hh_apply_worker` | cap, applied_today | Дневной лимит |
| `hh.session_expired` | `hh_apply_worker` | — | Сессия HH истекла |

---

## 7. Risk Assessment

| Риск | Вероятность | Импакт | Митигация |
|------|-------------|--------|-----------|
| HH блокирует аккаунт | Средняя | Высокий | Anti-ban delays, cap 20/day, human-like behavior |
| Селекторы HH изменились | Высокая | Средний | Селекторы в отдельном файле, graceful degradation |
| Session истекает | Высокая | Низкий | Auto-detect + TG notification + /bootstrap command |
| CAPTCHA | Средняя | Средний | Pause worker + TG notification + /resume_apply |
| Cover letter отсутствует | Низкая | Низкий | Apply без CL (HH позволяет) |
| Network timeout | Средняя | Низкий | Retry + exponential backoff per vacancy |

---

## 8. Что НЕ входит в PR-8 (post-MVP)

- ❌ Retry по расписанию (только ручной /retry_apply)
- ❌ Скриншот страницы при ошибке (future: useful для debug)
- ❌ Captcha solver (manual only)
- ❌ Random mouse movements (nice-to-have)
- ❌ Multiple HH accounts
- ❌ TG inline button "Я решил капчу" (только /resume_apply)
- ❌ Resume/CV selection (используем default resume на HH)
- ❌ Playwright в Docker (local only for MVP)

---

## 9. Prereqs от Кати

Перед началом имплементации:

1. **Подтвердить:** аккаунт HH логинится на машине разработки
2. **Запустить bootstrap:** `python -m connectors.hh_browser.bootstrap` → получить storage_state.json
3. **Найти 1-2 тестовых вакансии:** открытые, без теста, для smoke test
4. **Установить Playwright:** `pip install playwright && playwright install chromium`

---

## 10. MVP v1 completion criteria

После merge PR-8:

| Capability | PR | Status |
|------------|-----|--------|
| TG vacancy ingest | PR-1, PR-2 | ✅ |
| HH.ru vacancy ingest | PR-6 | ✅ |
| LLM scoring (0-10) | PR-3 | ✅ |
| Policy routing | PR-4 | ✅ |
| Telegram approval UX | PR-5 | ✅ |
| Cover letter generation | PR-7 | ✅ |
| **Automated HH apply** | **PR-8** | **🔄** |

**MVP v1 = PR-1..PR-8. После PR-8 merge → MVP v1 ЗАКРЫТ.**

End-to-end flow:
```
HH vacancy → Ingest → Score → Policy → Cover Letter → Auto-Apply → ✅
                                    ↗ Approval → Approve → Apply → ✅
```
