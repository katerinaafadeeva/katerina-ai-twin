# TASK: PR-8 — Playwright Auto-Apply (MVP v1 scope)

You are the Implementation Agent (Tech Lead). Work in branch `pr-8`.
Model: Sonnet. All explanations and final report must be in Russian.

**Do NOT re-architect PR-1–PR-7. Do NOT modify policy rules, scoring logic, cover letter generation, or HH ingest.**

## Context

PR-1..PR-7 are complete and merged. ~225 tests pass.
PR-8 adds Playwright-based automated job application on HH.ru.
Branch: `pr-8`

**MVP v1 scope:** Take scored + policy-routed vacancies with generated cover letters and physically apply to them on HH.ru via browser automation.

- AUTO_APPLY (score 5-6, source='hh', status='created') → auto-apply immediately
- APPROVAL_REQUIRED (score ≥7, status='approved') → apply after operator approval
- Test/questionnaire on vacancy → manual_required
- CAPTCHA → pause all applies, notify operator
- External link vacancy → manual_required
- Already applied → skip (idempotent)

**Read these files first:**
- `DECISIONS.md` — all business rules
- `capabilities/career_os/skills/match_scoring/worker.py` — scoring worker pattern
- `capabilities/career_os/skills/cover_letter/store.py` — cover letter retrieval
- `core/config.py` — config singleton pattern
- `core/events.py` — event emit pattern
- `core/db.py` — database connection pattern

**BUSINESS CONTRACT:**
- Only HH vacancies (source='hh') get auto-apply
- Cover letter from DB inserted into apply form (if textarea available)
- Daily cap APPLY_DAILY_CAP=20 (separate from scoring/CL caps)
- Human-like delays between applies (30-90 sec random)
- Feature flag HH_APPLY_ENABLED=false by default
- No LLM calls. Zero. This is pure execution.
- Session stored in identity/hh_storage_state.json (already gitignored)

---

## Step 1: Migration — extend actions for execution tracking

Create `core/migrations/008_apply_execution.sql`:

```sql
ALTER TABLE actions ADD COLUMN execution_status TEXT;
-- Values: NULL (not started), 'applying', 'applied', 'failed', 'manual_required'

ALTER TABLE actions ADD COLUMN execution_error TEXT;
-- Error details: 'has_test', 'external_link', 'captcha', 'network_error', 'session_expired', 'unknown_page', 'already_applied'

ALTER TABLE actions ADD COLUMN execution_attempts INTEGER DEFAULT 0;

ALTER TABLE actions ADD COLUMN applied_at TIMESTAMP;

ALTER TABLE actions ADD COLUMN hh_vacancy_id TEXT;
-- Extracted from HH vacancy URL or raw_text for URL construction

CREATE INDEX IF NOT EXISTS idx_actions_execution
ON actions(execution_status, action_type);
```

Verify: `python -c "from core.db import init_db; init_db(); print('Migration 008 OK')"`

Commit: `feat(core): migration 008 — extend actions with execution tracking fields`

---

## Step 2: Config — add apply settings

Add to `core/config.py`:

```python
# HH Apply settings
hh_apply_enabled: bool              # default False
apply_daily_cap: int                # default 20
apply_delay_min: int                # default 30 (seconds)
apply_delay_max: int                # default 90 (seconds)
apply_batch_size: int               # default 5
apply_worker_interval: int          # default 300 (seconds, 5 min)
hh_storage_state_path: str          # default "identity/hh_storage_state.json"
```

Update `.env.example`:
```
# === HH Auto-Apply (PR-8) ===
HH_APPLY_ENABLED=false
APPLY_DAILY_CAP=20
APPLY_DELAY_MIN=30
APPLY_DELAY_MAX=90
APPLY_BATCH_SIZE=5
APPLY_WORKER_INTERVAL=300
HH_STORAGE_STATE_PATH=identity/hh_storage_state.json
```

Commit: `feat(core): add HH apply config — feature flag, caps, delays`

---

## Step 3: HH Browser connector — selectors + client

### Create `connectors/hh_browser/__init__.py` — empty

### Create `connectors/hh_browser/selectors.py`

```python
"""HH.ru page selectors — extracted for maintainability.

HH.ru uses data-qa attributes which are more stable than CSS classes.
When HH changes their markup, update selectors here.
"""

# Vacancy page
VACANCY_TITLE = "[data-qa='vacancy-title']"
VACANCY_COMPANY = "[data-qa='vacancy-company-name']"

# Apply button
APPLY_BUTTON = "[data-qa='vacancy-response-link-top']"
APPLY_BUTTON_BOTTOM = "[data-qa='vacancy-response-link-bottom']"

# Already applied indicator
ALREADY_APPLIED = "[data-qa='vacancy-response-link-view-topic']"

# Test/questionnaire indicators
HAS_TEST_BADGE = "[data-qa='vacancy-response-link-test']"

# Apply form
COVER_LETTER_TEXTAREA = "[data-qa='vacancy-response-popup-form-letter-input']"
SUBMIT_BUTTON = "[data-qa='vacancy-response-submit-popup']"

# Success indicators
APPLY_SUCCESS = "[data-qa='vacancy-response-link-view-topic']"

# Login required
LOGIN_FORM = "[data-qa='login-input-username']"

# CAPTCHA indicators (text-based detection)
CAPTCHA_KEYWORDS = ["капча", "captcha", "подтвердите", "я не робот"]
```

### Create `connectors/hh_browser/client.py`

```python
"""Singleton Playwright browser client for HH.ru.

Manages persistent browser context with saved session.
One instance per application lifecycle.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ApplyStatus(str, Enum):
    APPLIED = "applied"
    FAILED = "failed"
    MANUAL_REQUIRED = "manual_required"
    ALREADY_APPLIED = "already_applied"
    SESSION_EXPIRED = "session_expired"
    CAPTCHA = "captcha"


@dataclass(frozen=True)
class ApplyResult:
    status: ApplyStatus
    error: str | None = None
    message: str | None = None


class HHBrowserClient:
    """Persistent Playwright browser for HH.ru automation."""

    def __init__(self, storage_state_path: str):
        self._storage_state_path = storage_state_path
        self._playwright = None
        self._browser = None
        self._context = None
        self._started = False

    async def start(self):
        """Launch browser with saved HH session."""
        from playwright.async_api import async_playwright

        if not Path(self._storage_state_path).exists():
            raise FileNotFoundError(
                f"HH storage state not found: {self._storage_state_path}. "
                "Run: python -m connectors.hh_browser.bootstrap"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            storage_state=self._storage_state_path,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        self._started = True
        logger.info("HH browser started with saved session")

    async def stop(self):
        """Save session state and close browser."""
        if self._context:
            try:
                await self._context.storage_state(path=self._storage_state_path)
                logger.info("HH session saved to %s", self._storage_state_path)
            except Exception:
                logger.exception("Failed to save HH session")
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    async def new_page(self):
        """Create new page in persistent context."""
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")
        return await self._context.new_page()
```

### Create `connectors/hh_browser/apply_flow.py`

```python
"""Step-by-step apply flow on HH.ru vacancy page.

Handles: success, already_applied, has_test, external_link, captcha, session_expired.
"""

import logging
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from connectors.hh_browser.client import ApplyResult, ApplyStatus
from connectors.hh_browser import selectors

logger = logging.getLogger(__name__)

NAVIGATION_TIMEOUT = 15_000  # 15 sec
ACTION_TIMEOUT = 10_000      # 10 sec


async def apply_to_vacancy(page: Page, vacancy_url: str, cover_letter: str | None) -> ApplyResult:
    """Execute full apply flow on a single HH vacancy.

    Steps:
    1. Navigate to vacancy page
    2. Check pre-conditions (login, already applied, test, external)
    3. Click apply button
    4. Fill cover letter (if textarea available)
    5. Submit and verify result

    Returns ApplyResult with status and optional error details.
    """
    try:
        # Step 1: Navigate
        await page.goto(vacancy_url, timeout=NAVIGATION_TIMEOUT, wait_until="domcontentloaded")

        # Step 2: Check for login page (session expired)
        if await page.query_selector(selectors.LOGIN_FORM):
            return ApplyResult(ApplyStatus.SESSION_EXPIRED, error="session_expired")

        # Step 3: Check for CAPTCHA
        page_text = (await page.content()).lower()
        if any(kw in page_text for kw in selectors.CAPTCHA_KEYWORDS):
            return ApplyResult(ApplyStatus.CAPTCHA, error="captcha")

        # Step 4: Already applied?
        if await page.query_selector(selectors.ALREADY_APPLIED):
            return ApplyResult(ApplyStatus.ALREADY_APPLIED, message="Уже откликались ранее")

        # Step 5: Has test/questionnaire?
        if await page.query_selector(selectors.HAS_TEST_BADGE):
            return ApplyResult(ApplyStatus.MANUAL_REQUIRED, error="has_test",
                             message="Вакансия требует тестовое задание")

        # Step 6: Find apply button
        apply_btn = await page.query_selector(selectors.APPLY_BUTTON)
        if not apply_btn:
            apply_btn = await page.query_selector(selectors.APPLY_BUTTON_BOTTOM)
        if not apply_btn:
            return ApplyResult(ApplyStatus.FAILED, error="no_apply_button",
                             message="Кнопка 'Откликнуться' не найдена")

        # Step 7: Check if button leads to external link
        href = await apply_btn.get_attribute("href")
        if href and not href.startswith("/") and "hh.ru" not in href:
            return ApplyResult(ApplyStatus.MANUAL_REQUIRED, error="external_link",
                             message=f"Отклик через внешнюю ссылку: {href}")

        # Step 8: Click apply
        await apply_btn.click()
        await page.wait_for_timeout(2000)  # Wait for popup/form

        # Step 9: Fill cover letter if textarea available
        if cover_letter:
            cl_textarea = await page.query_selector(selectors.COVER_LETTER_TEXTAREA)
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
                logger.info("Cover letter inserted (%d chars)", len(cover_letter))

        # Step 10: Submit
        submit_btn = await page.query_selector(selectors.SUBMIT_BUTTON)
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(3000)

        # Step 11: Verify success
        # After submit, check if "Вы откликнулись" indicator appeared
        success = await page.query_selector(selectors.APPLY_SUCCESS)
        if success:
            return ApplyResult(ApplyStatus.APPLIED, message="Отклик отправлен")

        # Check for captcha after submit
        page_text_after = (await page.content()).lower()
        if any(kw in page_text_after for kw in selectors.CAPTCHA_KEYWORDS):
            return ApplyResult(ApplyStatus.CAPTCHA, error="captcha_after_submit")

        # If no clear success/failure indicator — assume applied (optimistic)
        # This handles cases where HH redirects to response list
        return ApplyResult(ApplyStatus.APPLIED,
                          message="Отклик предположительно отправлен (нет явного подтверждения)")

    except PlaywrightTimeout:
        return ApplyResult(ApplyStatus.FAILED, error="timeout",
                          message="Таймаут при загрузке страницы")
    except Exception as e:
        logger.exception("Unexpected error during apply: %s", vacancy_url)
        return ApplyResult(ApplyStatus.FAILED, error="unexpected",
                          message=str(e)[:200])
```

### Create `connectors/hh_browser/bootstrap.py`

```python
"""Interactive login to HH.ru — run once to save session.

Usage: python -m connectors.hh_browser.bootstrap

Opens a visible browser, user logs in manually, session saved to storage_state.json.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from core.config import config


async def bootstrap_login():
    """Launch headed browser for manual HH.ru login."""
    storage_path = config.hh_storage_state_path
    print(f"🔐 Запуск браузера для авторизации на HH.ru")
    print(f"📁 Сессия будет сохранена в: {storage_path}")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        page = await context.new_page()
        await page.goto("https://hh.ru/account/login")

        print("👉 Войдите в аккаунт HH.ru в открывшемся браузере.")
        print("👉 После успешного входа нажмите Enter в терминале.")
        print()
        input("⏎ Нажмите Enter после авторизации... ")

        # Save session
        Path(storage_path).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=storage_path)
        print(f"✅ Сессия сохранена: {storage_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(bootstrap_login())
```

Commit: `feat(connectors): add HH browser connector — client, selectors, apply flow, bootstrap`

---

## Step 4: HH Apply skill — store

### Create `capabilities/career_os/skills/hh_apply/__init__.py` — empty

### Create `capabilities/career_os/skills/hh_apply/SKILL.md`

```markdown
---
name: hh_apply
description: Automated job application on HH.ru via Playwright browser automation
---

# HH Apply (v1 — Playwright)

## Input
- Pending actions (AUTO_APPLY created, APPROVAL_REQUIRED approved)
- Cover letters from cover_letters table
- HH browser session (storage_state.json)

## Output
- Updated execution_status on actions (applied/failed/manual_required)
- Audit events (hh.apply_*)
- Telegram notifications for results

## Business Rules
1. Only source='hh' vacancies
2. Daily cap: APPLY_DAILY_CAP (default 20)
3. Human-like delays between applies
4. CAPTCHA → pause all, notify operator
5. Test/external/questionnaire → manual_required
6. Session expired → notify operator
7. Feature flag: HH_APPLY_ENABLED (default false)

## No LLM
This skill is pure execution. Zero LLM calls.
```

### Create `capabilities/career_os/skills/hh_apply/store.py`

```python
"""Apply task queue and execution status management.

Handles: pending task selection, status updates, daily cap counting.
"""

import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def get_pending_apply_tasks(conn: sqlite3.Connection, batch_size: int = 5) -> list[dict]:
    """Get next batch of tasks ready for auto-apply.

    Returns tasks from two sources:
    1. AUTO_APPLY with status='created' and no execution_status
    2. APPROVAL_REQUIRED with status='approved' and no execution_status

    Only HH vacancies (source='hh'). Ordered by created_at ASC (oldest first).
    Max 3 days old.
    """
    rows = conn.execute("""
        SELECT a.id as action_id, a.job_raw_id, a.action_type, a.hh_vacancy_id,
               jr.raw_text, jr.source_id,
               cl.letter_text as cover_letter
        FROM actions a
        JOIN job_raw jr ON jr.id = a.job_raw_id
        LEFT JOIN cover_letters cl ON cl.job_raw_id = a.job_raw_id
        WHERE jr.source = 'hh'
          AND a.execution_status IS NULL
          AND (
              (a.action_type = 'AUTO_APPLY' AND a.status = 'created')
              OR
              (a.action_type = 'APPROVAL_REQUIRED' AND a.status = 'approved')
          )
          AND date(a.created_at) >= date('now', '-3 days')
        ORDER BY a.created_at ASC
        LIMIT ?
    """, (batch_size,)).fetchall()
    return [dict(r) for r in rows]


def update_execution_status(
    conn: sqlite3.Connection,
    action_id: int,
    execution_status: str,
    error: str | None = None,
    hh_vacancy_id: str | None = None,
) -> None:
    """Update execution status on action."""
    now = datetime.utcnow().isoformat()
    applied_at = now if execution_status == "applied" else None

    conn.execute("""
        UPDATE actions
        SET execution_status = ?,
            execution_error = ?,
            execution_attempts = execution_attempts + 1,
            applied_at = COALESCE(?, applied_at),
            hh_vacancy_id = COALESCE(?, hh_vacancy_id),
            updated_at = ?
        WHERE id = ?
    """, (execution_status, error, applied_at, hh_vacancy_id, now, action_id))
    conn.commit()


def mark_applying(conn: sqlite3.Connection, action_id: int) -> None:
    """Mark action as currently being applied (lock)."""
    conn.execute("""
        UPDATE actions
        SET execution_status = 'applying',
            execution_attempts = execution_attempts + 1,
            updated_at = ?
        WHERE id = ?
    """, (datetime.utcnow().isoformat(), action_id))
    conn.commit()


def get_today_apply_count(conn: sqlite3.Connection) -> int:
    """Count successful applies today."""
    row = conn.execute("""
        SELECT COUNT(*) FROM actions
        WHERE execution_status = 'applied'
        AND date(applied_at) = date('now')
    """).fetchone()
    return row[0]


def extract_hh_vacancy_id(raw_text: str, source_id: str | None = None) -> str | None:
    """Extract HH vacancy ID from raw text or source_id.

    HH vacancy URLs look like: https://hh.ru/vacancy/12345678
    source_id from HH ingest should already contain the vacancy ID.
    """
    if source_id and source_id.isdigit():
        return source_id

    import re
    match = re.search(r'hh\.ru/vacancy/(\d+)', raw_text or '')
    return match.group(1) if match else None


def build_vacancy_url(hh_vacancy_id: str) -> str:
    """Build HH.ru vacancy URL from ID."""
    return f"https://hh.ru/vacancy/{hh_vacancy_id}"
```

Commit: `feat(career_os): add hh_apply skill — store with task queue and execution status`

---

## Step 5: HH Apply worker

### Create `capabilities/career_os/skills/hh_apply/worker.py`

```python
"""Async worker that processes apply queue via Playwright.

Picks pending tasks → opens browser → applies → updates status → notifies.
Respects daily cap, delays, and feature flag.
"""

import asyncio
import logging
import random

from core.config import config
from core.db import get_conn
from core.events import emit

from connectors.hh_browser.client import HHBrowserClient, ApplyStatus
from connectors.hh_browser.apply_flow import apply_to_vacancy

from capabilities.career_os.skills.hh_apply.store import (
    get_pending_apply_tasks,
    update_execution_status,
    mark_applying,
    get_today_apply_count,
    extract_hh_vacancy_id,
    build_vacancy_url,
)

logger = logging.getLogger(__name__)


async def run_apply_cycle(browser: HHBrowserClient, notify_callback=None):
    """Run one cycle of the apply worker.

    1. Check daily cap
    2. Get pending tasks
    3. For each task: apply via browser, update DB, emit event
    4. Send summary notification

    Args:
        browser: Started HHBrowserClient instance
        notify_callback: async func(message: str) for Telegram notifications
    """
    conn = get_conn()

    # Check daily cap
    applied_today = get_today_apply_count(conn)
    if applied_today >= config.apply_daily_cap:
        logger.info("Apply daily cap reached: %d/%d", applied_today, config.apply_daily_cap)
        emit(conn, "hh.apply_cap_reached",
             {"cap": config.apply_daily_cap, "applied_today": applied_today},
             actor="hh_apply_worker")
        return

    remaining = config.apply_daily_cap - applied_today
    batch_size = min(config.apply_batch_size, remaining)

    # Get pending tasks
    tasks = get_pending_apply_tasks(conn, batch_size=batch_size)
    if not tasks:
        logger.debug("No pending apply tasks")
        return

    logger.info("Apply cycle: %d tasks, %d/%d daily cap",
                len(tasks), applied_today, config.apply_daily_cap)

    results = []
    captcha_hit = False

    for i, task in enumerate(tasks):
        if captcha_hit:
            break  # Stop batch on captcha

        action_id = task["action_id"]
        job_raw_id = task["job_raw_id"]
        cover_letter = task.get("cover_letter")

        # Extract vacancy ID
        hh_vacancy_id = extract_hh_vacancy_id(
            task.get("raw_text", ""),
            task.get("source_id")
        )
        if not hh_vacancy_id:
            update_execution_status(conn, action_id, "failed",
                                   error="no_vacancy_id")
            emit(conn, "hh.apply_failed",
                 {"action_id": action_id, "error": "no_vacancy_id"},
                 actor="hh_apply_worker")
            results.append(("failed", action_id, "No vacancy ID"))
            continue

        vacancy_url = build_vacancy_url(hh_vacancy_id)

        # Mark as applying
        mark_applying(conn, action_id)
        emit(conn, "hh.apply_started",
             {"action_id": action_id, "vacancy_url": vacancy_url},
             actor="hh_apply_worker")

        # Execute apply
        try:
            page = await browser.new_page()
            try:
                result = await apply_to_vacancy(page, vacancy_url, cover_letter)
            finally:
                await page.close()
        except Exception as e:
            logger.exception("Browser error for action %d", action_id)
            result = None

        if result is None:
            update_execution_status(conn, action_id, "failed",
                                   error="browser_error", hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.apply_failed",
                 {"action_id": action_id, "error": "browser_error"},
                 actor="hh_apply_worker")
            results.append(("failed", action_id, "Browser error"))
            continue

        # Process result
        if result.status == ApplyStatus.APPLIED:
            update_execution_status(conn, action_id, "applied",
                                   hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.apply_succeeded",
                 {"action_id": action_id, "vacancy_url": vacancy_url},
                 actor="hh_apply_worker")
            results.append(("applied", action_id, result.message))

        elif result.status == ApplyStatus.ALREADY_APPLIED:
            update_execution_status(conn, action_id, "applied",
                                   error="already_applied", hh_vacancy_id=hh_vacancy_id)
            results.append(("applied", action_id, "Уже откликались"))

        elif result.status == ApplyStatus.MANUAL_REQUIRED:
            update_execution_status(conn, action_id, "manual_required",
                                   error=result.error, hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.apply_manual_required",
                 {"action_id": action_id, "reason": result.error,
                  "vacancy_url": vacancy_url},
                 actor="hh_apply_worker")
            results.append(("manual", action_id, result.message))

        elif result.status == ApplyStatus.CAPTCHA:
            update_execution_status(conn, action_id, "failed",
                                   error="captcha", hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.apply_captcha",
                 {"action_id": action_id}, actor="hh_apply_worker")
            captcha_hit = True
            results.append(("captcha", action_id, "CAPTCHA"))

        elif result.status == ApplyStatus.SESSION_EXPIRED:
            update_execution_status(conn, action_id, "failed",
                                   error="session_expired", hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.session_expired", {}, actor="hh_apply_worker")
            captcha_hit = True  # Stop processing
            results.append(("session", action_id, "Session expired"))

        else:  # FAILED
            update_execution_status(conn, action_id, "failed",
                                   error=result.error, hh_vacancy_id=hh_vacancy_id)
            emit(conn, "hh.apply_failed",
                 {"action_id": action_id, "error": result.error},
                 actor="hh_apply_worker")
            results.append(("failed", action_id, result.message))

        # Human-like delay between applies (skip after last one)
        if i < len(tasks) - 1 and not captcha_hit:
            delay = random.uniform(config.apply_delay_min, config.apply_delay_max)
            logger.info("Delay before next apply: %.0f sec", delay)
            await asyncio.sleep(delay)

    # Send summary notification
    if notify_callback and results:
        msg = _format_apply_summary(results, applied_today + len(
            [r for r in results if r[0] == "applied"]))
        await notify_callback(msg)

    if captcha_hit and notify_callback:
        await notify_callback(
            "🛑 *Captcha на HH.ru*\n\n"
            "Автоматические отклики приостановлены.\n"
            "Зайдите на HH.ru, решите капчу,\n"
            "затем отправьте /resume_apply"
        )

    conn.close()


def _format_apply_summary(results: list, total_today: int) -> str:
    """Format apply results as Telegram message."""
    applied = sum(1 for r in results if r[0] == "applied")
    total = len(results)

    lines = [f"📋 *Автоотклики: {applied} из {total}*\n"]
    for status, action_id, message in results:
        if status == "applied":
            lines.append(f"✅ #{action_id}: {message or 'Отклик отправлен'}")
        elif status == "manual":
            lines.append(f"⚠️ #{action_id}: {message or 'Требуется вручную'}")
        elif status == "captcha":
            lines.append(f"🛑 #{action_id}: Captcha")
        elif status == "session":
            lines.append(f"🔑 #{action_id}: Сессия истекла")
        else:
            lines.append(f"❌ #{action_id}: {message or 'Ошибка'}")

    from core.config import config
    lines.append(f"\n📊 Сегодня: {total_today}/{config.apply_daily_cap}")
    return "\n".join(lines)


async def apply_worker_loop(browser: HHBrowserClient, notify_callback=None):
    """Infinite loop running apply cycles with interval.

    Meant to be started as asyncio.Task in telegram_bot.py.
    """
    logger.info("Apply worker started (interval=%ds)", config.apply_worker_interval)
    while True:
        try:
            await run_apply_cycle(browser, notify_callback)
        except Exception:
            logger.exception("Apply worker cycle error")
        await asyncio.sleep(config.apply_worker_interval)
```

Commit: `feat(career_os): add hh_apply worker — browser-based apply with cap, delays, notifications`

---

## Step 6: Telegram integration — register worker + /resume_apply

Update `connectors/telegram_bot.py`:

1. Import apply worker
2. Start apply worker as asyncio.Task behind HH_APPLY_ENABLED flag
3. Add `/resume_apply` command handler
4. Pass notify callback to worker

**Key integration points:**

```python
# In on_startup or equivalent:
if config.hh_apply_enabled:
    from connectors.hh_browser.client import HHBrowserClient
    from capabilities.career_os.skills.hh_apply.worker import apply_worker_loop

    browser = HHBrowserClient(config.hh_storage_state_path)
    await browser.start()

    async def notify(msg: str):
        await bot.send_message(OWNER_CHAT_ID, msg, parse_mode="Markdown")

    asyncio.create_task(apply_worker_loop(browser, notify_callback=notify))

# /resume_apply command:
@dp.message(Command("resume_apply"))
async def cmd_resume_apply(message: Message):
    """Resume apply worker after manual captcha resolution."""
    if not is_authorized(message):
        return
    # Worker already runs in a loop — next cycle will pick up pending tasks
    await message.reply("✅ Отклики возобновлены. Следующий цикл через ~5 мин.")
```

**Handle manual_required notifications:**

When a vacancy gets manual_required status, send Telegram notification:

```python
# In hh_apply/notifier.py
async def notify_manual_required(notify_callback, action_id, vacancy_url, reason):
    reason_text = {
        "has_test": "тестовое задание",
        "external_link": "отклик через внешнюю ссылку",
        "captcha": "капча",
    }.get(reason, reason)

    msg = (
        f"⚠️ *Требуется ручной отклик*\n\n"
        f"📋 Action #{action_id}\n"
        f"🔗 {vacancy_url}\n"
        f"❌ Причина: {reason_text}\n\n"
        f"Откликнитесь вручную на HH.ru"
    )
    await notify_callback(msg)
```

Commit: `feat(bot): integrate apply worker — feature flag, /resume_apply, notifications`

---

## Step 7: Notifier module

### Create `capabilities/career_os/skills/hh_apply/notifier.py`

Full notifier with manual_required, captcha, session_expired, and batch summary notifications.

Commit: `feat(career_os): add apply notifier — TG notifications for all apply outcomes`

---

## Step 8: Tests

### Create `tests/test_hh_apply_store.py`

```python
# Tests for store.py:
# - test_get_pending_auto_apply: AUTO_APPLY created → returned
# - test_get_pending_approved: APPROVAL_REQUIRED approved → returned
# - test_skip_non_hh_source: TG source → not returned
# - test_skip_already_executing: execution_status='applying' → not returned
# - test_skip_old_actions: >3 days old → not returned
# - test_update_execution_applied: status + applied_at set
# - test_update_execution_failed: error field set
# - test_daily_count: counts only applied today
# - test_extract_hh_vacancy_id: from URL, from source_id
# - test_mark_applying: increments attempts
```

### Create `tests/test_hh_apply_worker.py`

```python
# Tests for worker.py (mock browser):
# - test_apply_cycle_empty_queue: no pending → no browser calls
# - test_apply_cycle_success: mock APPLIED → status updated, event emitted
# - test_apply_cycle_manual_required: mock MANUAL → status updated, event emitted
# - test_apply_cycle_captcha_stops_batch: captcha → remaining tasks skipped
# - test_apply_cycle_cap_reached: cap full → no applies
# - test_apply_cycle_delay_between: verify delays called
# - test_apply_cycle_session_expired: session → stops batch + event
```

### Create `tests/test_hh_apply_flow.py`

```python
# Tests for apply_flow.py (mock Playwright page):
# - test_apply_success: mock success selectors → APPLIED
# - test_already_applied: mock already_applied selector → ALREADY_APPLIED
# - test_has_test: mock test badge → MANUAL_REQUIRED
# - test_external_link: mock external href → MANUAL_REQUIRED
# - test_session_expired: mock login form → SESSION_EXPIRED
# - test_captcha_detected: mock captcha text → CAPTCHA
# - test_no_apply_button: no button found → FAILED
# - test_timeout: mock timeout → FAILED
# - test_cover_letter_inserted: verify fill() called on textarea
```

**All tests mock Playwright — no real browser in tests.**

Commit: `test: add hh_apply tests — store, worker, apply flow (all mocked)`

---

## Step 9: Documentation

### Update `STATUS.md`:
- PR-8: ✅ DONE — Playwright Auto-Apply
- MVP v1: ✅ COMPLETE

### Update `CHANGELOG.md` — add PR-8 section:
```markdown
## PR-8: Playwright Auto-Apply (HH.ru)

### Added
- `connectors/hh_browser/` — Playwright browser client, selectors, apply flow, bootstrap
- `capabilities/career_os/skills/hh_apply/` — store, worker, notifier, SKILL.md
- `core/migrations/008_apply_execution.sql` — execution tracking fields
- Config: HH_APPLY_ENABLED, APPLY_DAILY_CAP, delay/batch settings
- /resume_apply command for resuming after captcha
- ~30 new tests; ~255 total

### Changed
- `telegram_bot.py` — apply worker registration behind feature flag
- `.env.example` — HH apply environment variables

### New events
| Event | Actor | Payload |
|---|---|---|
| `hh.apply_started` | `hh_apply_worker` | action_id, vacancy_url |
| `hh.apply_succeeded` | `hh_apply_worker` | action_id, vacancy_url |
| `hh.apply_failed` | `hh_apply_worker` | action_id, error, attempts |
| `hh.apply_manual_required` | `hh_apply_worker` | action_id, reason |
| `hh.apply_captcha` | `hh_apply_worker` | action_id |
| `hh.apply_cap_reached` | `hh_apply_worker` | cap, applied_today |
| `hh.session_expired` | `hh_apply_worker` | — |
```

### Update `DECISIONS.md` — add PR-8 section:
```markdown
## PR-8 Decisions (Playwright Auto-Apply) (2026-02-XX)

### Execution status separate from business status
actions.status = business decision (created/approved/rejected/snoozed)
actions.execution_status = technical execution (applying/applied/failed/manual_required)
Rationale: these are different concerns.

### No separate apply_runs table (MVP)
Execution tracked in actions table. For 20 applies/day, overhead of separate table
not justified. Revisit if apply volume increases significantly.

### Persistent browser context (singleton)
One browser instance reused across applies. storage_state.json saves session.
Rationale: avoids re-login on every apply, reduces HH detection risk.

### Feature flag HH_APPLY_ENABLED=false
Apply worker doesn't start unless explicitly enabled.
Rationale: safety — prevents accidental auto-applies during development/testing.

### CAPTCHA pauses all applies
Single captcha → stop entire batch → notify operator → wait for /resume_apply.
Rationale: continuing after captcha likely means all subsequent requests will also be challenged.

### No auto-retry for failed applies (MVP)
Failed applies stay as 'failed'. Retry only via operator command.
Rationale: auto-retry risks HH rate limiting. Manual review of failures preferred.

### Selectors in separate file
connectors/hh_browser/selectors.py — all CSS/data-qa selectors extracted.
Rationale: HH.ru changes markup periodically. Centralized update point.
```

### Update `BACKLOG.md` — PR-8 DONE, MVP v1 COMPLETE

Commit: `docs: update STATUS, CHANGELOG, DECISIONS, BACKLOG for PR-8 — MVP v1 complete`

---

## How to verify

```bash
# Tests
python3 -m pytest -q
# Expected: ~255 tests, all green

# Config check
python -c "from core.config import config; print('Apply enabled:', config.hh_apply_enabled, 'Cap:', config.apply_daily_cap)"

# Migration check
python -c "from core.db import init_db; init_db(); print('OK')"

# Selectors present
python -c "from connectors.hh_browser import selectors; print('Apply button:', selectors.APPLY_BUTTON)"

# Store functions
python -c "from capabilities.career_os.skills.hh_apply.store import extract_hh_vacancy_id; print(extract_hh_vacancy_id('https://hh.ru/vacancy/123456'))"

# Manual smoke test (requires HH session):
# 1. Set HH_APPLY_ENABLED=true in .env
# 2. Run bootstrap: python -m connectors.hh_browser.bootstrap
# 3. Ensure 1-2 test vacancies are in DB with AUTO_APPLY status
# 4. Start bot, wait for apply cycle
# 5. Check Telegram: apply summary notification
# 6. Check SQLite: SELECT * FROM actions WHERE execution_status IS NOT NULL;
# 7. Check events: SELECT * FROM events WHERE event_name LIKE 'hh.apply%';
```

---

## Final Report (write in Russian)

After all steps, generate a report:
1. Что реализовано (файлы, строки, решения)
2. Какие файлы изменены/созданы
3. Результаты тестов (pytest output)
4. Подтверждение: policy rules НЕ изменены
5. Подтверждение: scoring logic НЕ изменена
6. Подтверждение: cover letter logic НЕ изменена
7. Подтверждение: zero LLM calls added
8. Подтверждение: feature flag работает (disabled by default)
9. Количество файлов/строк
10. Список TODO для post-MVP (retry, screenshots, Docker)
11. MVP v1 completion status
