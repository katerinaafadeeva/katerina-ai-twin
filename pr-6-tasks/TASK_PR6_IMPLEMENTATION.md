# TASK: PR-6 — HH Ingest v0.1

You are the Implementation Agent (Tech Lead). Work in branch `pr-6`.
Model: Sonnet. All explanations and final report must be in Russian.

**Do NOT re-architect PR-3/PR-4/PR-5. Do NOT modify policy rules or scoring logic.**

## Context

PR-5 (Telegram approval UX) is complete and merged. 130 tests pass.
PR-6 adds HH.ru vacancy ingestion via official API.
Branch: `pr6-hh-ingest`

**Read these files first:**
- `DECISIONS.md` (all business rules — especially policy routing for source='hh')
- `capabilities/career_os/skills/vacancy_ingest_telegram/handler.py` (existing ingest pattern)
- `capabilities/career_os/skills/match_scoring/worker.py` (worker pattern)
- `core/config.py` (config singleton)
- `core/db.py` (DB pattern)
- `core/events.py` (emit pattern)
- `identity/profile.example.json` (profile fields — negative_signals, industries_excluded)

**BUSINESS CONTRACT (unchanged from PR-4):**
- source='hh', score 5-6, within limit → AUTO_APPLY
- source='hh', score ≥7 → APPROVAL_REQUIRED
- source='hh', score <5 → IGNORE
- Daily limit counts AUTO_QUEUE + AUTO_APPLY both

**KEY DESIGN DECISION:** HH.ru official API (`GET https://api.hh.ru/vacancies`). Anonymous access (no OAuth). Search queries defined in `identity/hh_searches.json`.

---

## Step 1: Migration — Add hh_vacancy_id to job_raw

Create `core/migrations/006_job_raw_hh_id.sql`:

```sql
ALTER TABLE job_raw ADD COLUMN hh_vacancy_id TEXT;
CREATE INDEX IF NOT EXISTS idx_job_raw_hh_id ON job_raw(hh_vacancy_id);
```

Verify: `python -c "from core.db import init_db; init_db(); print('Migration 006 OK')"`

Commit: `feat(core): migration 006 — add hh_vacancy_id column + index to job_raw`

---

## Step 2: Config — Add HH settings

Modify `core/config.py`. Add fields to Config dataclass:

```python
hh_enabled: bool
hh_poll_interval: int          # seconds between HH poll cycles, default 3600
hh_user_agent: str             # User-Agent for HH API
hh_max_pages: int              # max search result pages to fetch, default 5
hh_scoring_daily_cap: int      # max LLM scoring calls per day, default 100
hh_searches_path: str          # path to search queries JSON
```

Add to `from_env()`:
```python
hh_enabled=os.getenv("HH_ENABLED", "false").lower() in ("true", "1", "yes"),
hh_poll_interval=int(os.getenv("HH_POLL_INTERVAL", "3600")),
hh_user_agent=os.getenv("HH_USER_AGENT", "KaterinaAITwin/0.1"),
hh_max_pages=int(os.getenv("HH_MAX_PAGES", "5")),
hh_scoring_daily_cap=int(os.getenv("HH_SCORING_DAILY_CAP", "100")),
hh_searches_path=os.getenv("HH_SEARCHES_PATH", "identity/hh_searches.json"),
```

Update `.env.example`:
```
# HH.ru integration
HH_ENABLED=false
HH_POLL_INTERVAL=3600
HH_USER_AGENT=KaterinaAITwin/0.1
HH_MAX_PAGES=5
HH_SCORING_DAILY_CAP=100
HH_SEARCHES_PATH=identity/hh_searches.json
```

Update `.gitignore` — add:
```
identity/hh_searches.json
```

Create `identity/hh_searches.example.json`:
```json
[
  {
    "text": "Product Manager",
    "area": "1",
    "schedule": "remote",
    "experience": "between3And6"
  },
  {
    "text": "Product Owner fintech",
    "area": "113"
  }
]
```

Update `requirements.txt` — add:
```
httpx>=0.27,<1
```

Commit: `feat(core): add HH config, search queries template, httpx dependency`

---

## Step 3: HH API Connector

Create `connectors/hh_api.py`:

```python
"""HH.ru API client — vacancy search with rate limiting and retry.

Anonymous access only (no OAuth). Requires User-Agent header.
Rate limited: max 1 request per second.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

HH_BASE_URL = "https://api.hh.ru"
DEFAULT_PER_PAGE = 100
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # exponential backoff base


class HHApiClient:
    """Async client for HH.ru vacancy search API.
    
    Features:
    - Rate limiting (1 req/sec)
    - Retry with exponential backoff on 429/5xx
    - Pagination support
    - Graceful error handling
    """

    def __init__(self, user_agent: str, max_pages: int = 5):
        self.user_agent = user_agent
        self.max_pages = max_pages
        self._last_request_time: float = 0.0

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self, client: httpx.AsyncClient, url: str, params: Dict[str, Any]
    ) -> Optional[Dict]:
        """Make a single HTTP request with retry logic."""
        for attempt in range(MAX_RETRIES):
            await self._rate_limit()
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "HH API rate limit (429), retry in %.1fs",
                        delay,
                        extra={"attempt": attempt + 1},
                    )
                    await asyncio.sleep(delay)
                elif response.status_code >= 500:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "HH API server error %d, retry in %.1fs",
                        response.status_code,
                        delay,
                        extra={"attempt": attempt + 1},
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "HH API unexpected status %d",
                        response.status_code,
                    )
                    return None
            except httpx.TimeoutException:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "HH API timeout, retry in %.1fs",
                    delay,
                    extra={"attempt": attempt + 1},
                )
                await asyncio.sleep(delay)
            except httpx.HTTPError as e:
                logger.error("HH API HTTP error: %s", str(e))
                return None

        logger.error("HH API max retries exhausted")
        return None

    async def search_vacancies(
        self, query_params: Dict[str, str]
    ) -> List[Dict]:
        """Search HH.ru vacancies with pagination.
        
        Args:
            query_params: Dict with search parameters (text, area, schedule, etc.)
            
        Returns:
            List of vacancy dicts from HH API response items.
        """
        all_items: List[Dict] = []
        params = {**query_params, "per_page": str(DEFAULT_PER_PAGE), "page": "0"}
        # Only fetch vacancies published in last 7 days
        if "period" not in params:
            params["period"] = "7"

        async with httpx.AsyncClient() as client:
            for page in range(self.max_pages):
                params["page"] = str(page)
                data = await self._request(
                    client, f"{HH_BASE_URL}/vacancies", params
                )
                if data is None:
                    break

                items = data.get("items", [])
                if not items:
                    break

                all_items.extend(items)
                logger.info(
                    "HH search page %d: %d items (total so far: %d)",
                    page, len(items), len(all_items),
                )

                # Stop if we've fetched all available
                total_pages = data.get("pages", 0)
                if page + 1 >= total_pages:
                    break

        return all_items
```

Commit: `feat(connectors): add HH.ru API client with rate limiting and retry`

---

## Step 4: HH Ingest Skill — store, prefilter, handler

### Create `capabilities/career_os/skills/vacancy_ingest_hh/__init__.py` — empty

### Create `capabilities/career_os/skills/vacancy_ingest_hh/SKILL.md`

```markdown
---
name: vacancy_ingest_hh
description: Pulls vacancies from HH.ru API and feeds them into the scoring pipeline
---

# Vacancy Ingest — HH.ru (v0.1)

## When activated
- Background worker polls HH API on configurable interval (default 1h)
- Uses search queries defined in identity/hh_searches.json

## What it does
1. Fetches vacancy search results from HH.ru API (paginated)
2. Pre-filters: rejects vacancies with negative signals (deterministic, no LLM)
3. Deduplicates: by hh_vacancy_id and canonical_key
4. Saves to job_raw with source="hh"
5. Emits vacancy.ingested event for each new vacancy

## Output
- job_raw records with source="hh"
- Events: vacancy.ingested, hh.search_completed

## Security
- Anonymous API access (no OAuth token stored)
- Search queries in gitignored JSON file
- Vacancy content not logged

## No LLM
Ingestion is purely deterministic. Scoring handled by existing worker.
```

### Create `capabilities/career_os/skills/vacancy_ingest_hh/prefilter.py`

```python
"""Deterministic pre-filter for HH vacancies.

Rejects obvious mismatches before LLM scoring to save tokens.
No LLM calls. Uses profile.negative_signals and industries_excluded.
"""

import logging
from typing import Tuple

from capabilities.career_os.models import Profile

logger = logging.getLogger(__name__)


def should_score(vacancy_text: str, profile: Profile) -> Tuple[bool, str]:
    """Check if vacancy should be sent to LLM scoring.

    Returns (True, "") if vacancy passes filter.
    Returns (False, reason) if vacancy is rejected.
    """
    text_lower = vacancy_text.lower()

    for signal in profile.negative_signals:
        if signal.lower() in text_lower:
            return False, f"negative_signal: {signal}"

    for industry in profile.industries_excluded:
        if industry.lower() in text_lower:
            return False, f"excluded_industry: {industry}"

    return True, ""
```

### Create `capabilities/career_os/skills/vacancy_ingest_hh/store.py`

```python
"""Persistence for HH vacancy ingestion.

All functions accept sqlite3.Connection. No get_conn() inside.
"""

import hashlib
import logging
import sqlite3
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _canonical_key(text: str) -> str:
    """Generate canonical key for cross-source dedup."""
    normalized = text.strip().lower()[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def is_hh_vacancy_ingested(conn: sqlite3.Connection, hh_vacancy_id: str) -> bool:
    """Check if HH vacancy was already ingested by its HH ID."""
    row = conn.execute(
        "SELECT 1 FROM job_raw WHERE hh_vacancy_id = ? LIMIT 1",
        (hh_vacancy_id,),
    ).fetchone()
    return row is not None


def get_today_scored_count(conn: sqlite3.Connection) -> int:
    """Count vacancies scored today (for daily cap enforcement)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM job_scores WHERE date(scored_at) = date('now')"
    ).fetchone()
    return row[0] if row else 0


def save_hh_vacancy(
    conn: sqlite3.Connection,
    hh_vacancy_id: str,
    raw_text: str,
    source_url: str,
) -> Tuple[int, bool]:
    """Save HH vacancy to job_raw. Returns (job_raw_id, is_new).

    Dedup by (source, source_message_id) via UNIQUE index.
    Also sets hh_vacancy_id for fast lookups.
    """
    source_message_id = f"hh_{hh_vacancy_id}"
    canonical_key = _canonical_key(raw_text)

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO job_raw
            (raw_text, source, source_message_id, canonical_key, hh_vacancy_id)
        VALUES (?, 'hh', ?, ?, ?)
        """,
        (raw_text, source_message_id, canonical_key, hh_vacancy_id),
    )

    if cursor.rowcount == 1:
        return cursor.lastrowid, True

    # Already exists — find existing row
    row = conn.execute(
        "SELECT id FROM job_raw WHERE source = 'hh' AND source_message_id = ?",
        (source_message_id,),
    ).fetchone()
    return row["id"] if row else 0, False
```

### Create `capabilities/career_os/skills/vacancy_ingest_hh/handler.py`

```python
"""Orchestration for HH vacancy ingestion.

Connects HH API client → pre-filter → store → events.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.prefilter import should_score
from capabilities.career_os.skills.vacancy_ingest_hh.store import (
    is_hh_vacancy_ingested,
    save_hh_vacancy,
)
from core.db import get_conn
from core.events import emit

logger = logging.getLogger(__name__)


def load_search_queries(path: str) -> List[Dict[str, str]]:
    """Load HH search queries from JSON file.

    Returns empty list if file not found (logged as warning).
    """
    p = Path(path)
    if not p.exists():
        logger.warning("HH searches file not found: %s", path)
        return []
    with open(p, "r", encoding="utf-8") as f:
        queries = json.load(f)
    if not isinstance(queries, list):
        logger.error("HH searches file must contain a JSON array")
        return []
    return queries


def normalize_vacancy(item: Dict[str, Any]) -> Dict[str, str]:
    """Extract relevant fields from HH API vacancy item.

    Builds raw_text from name + snippet for scoring.
    """
    name = item.get("name", "")
    employer_name = ""
    employer = item.get("employer")
    if isinstance(employer, dict):
        employer_name = employer.get("name", "")

    snippet = item.get("snippet", {}) or {}
    requirement = snippet.get("requirement", "") or ""
    responsibility = snippet.get("responsibility", "") or ""

    # Salary info
    salary_str = ""
    salary = item.get("salary")
    if isinstance(salary, dict) and salary:
        parts = []
        if salary.get("from"):
            parts.append(f"от {salary['from']}")
        if salary.get("to"):
            parts.append(f"до {salary['to']}")
        currency = salary.get("currency", "")
        if parts:
            salary_str = " ".join(parts) + f" {currency}"

    # Area (city)
    area_name = ""
    area = item.get("area")
    if isinstance(area, dict):
        area_name = area.get("name", "")

    # Schedule
    schedule_name = ""
    schedule = item.get("schedule")
    if isinstance(schedule, dict):
        schedule_name = schedule.get("name", "")

    # Build raw_text for scoring (same format as manual TG forwards)
    raw_parts = [f"Позиция: {name}"]
    if employer_name:
        raw_parts.append(f"Компания: {employer_name}")
    if area_name:
        raw_parts.append(f"Город: {area_name}")
    if schedule_name:
        raw_parts.append(f"Формат: {schedule_name}")
    if salary_str:
        raw_parts.append(f"ЗП: {salary_str}")
    if requirement:
        raw_parts.append(f"\nТребования:\n{_strip_html(requirement)}")
    if responsibility:
        raw_parts.append(f"\nОбязанности:\n{_strip_html(responsibility)}")

    raw_text = "\n".join(raw_parts)
    hh_id = str(item.get("id", ""))
    source_url = item.get("alternate_url", "")

    return {
        "hh_vacancy_id": hh_id,
        "raw_text": raw_text,
        "source_url": source_url,
    }


def _strip_html(text: str) -> str:
    """Remove basic HTML tags from HH API snippets."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def ingest_hh_vacancies(
    vacancies: List[Dict[str, Any]],
    profile: Profile,
) -> Dict[str, int]:
    """Process a batch of HH API vacancy items.

    Returns dict with counts: total, new, duplicate, filtered.
    """
    counts = {"total": 0, "new": 0, "duplicate": 0, "filtered": 0}

    for item in vacancies:
        counts["total"] += 1
        normalized = normalize_vacancy(item)
        hh_id = normalized["hh_vacancy_id"]

        if not hh_id:
            logger.warning("HH vacancy missing id, skipping")
            continue

        # Check dedup before heavy processing
        with get_conn() as conn:
            if is_hh_vacancy_ingested(conn, hh_id):
                counts["duplicate"] += 1
                continue

        # Pre-filter
        passes, reason = should_score(normalized["raw_text"], profile)
        if not passes:
            logger.debug(
                "HH vacancy %s pre-filtered: %s", hh_id, reason
            )
            counts["filtered"] += 1
            # Still save to DB (for analytics) but mark in event
            with get_conn() as conn:
                job_raw_id, is_new = save_hh_vacancy(
                    conn,
                    hh_id,
                    normalized["raw_text"],
                    normalized["source_url"],
                )
                conn.commit()
            if is_new:
                emit(
                    "vacancy.ingested",
                    {
                        "job_raw_id": job_raw_id,
                        "source": "hh",
                        "hh_vacancy_id": hh_id,
                        "pre_filtered": True,
                        "filter_reason": reason,
                    },
                    actor="hh_ingest",
                )
            continue

        # Save to job_raw
        with get_conn() as conn:
            job_raw_id, is_new = save_hh_vacancy(
                conn,
                hh_id,
                normalized["raw_text"],
                normalized["source_url"],
            )
            conn.commit()

        if is_new:
            counts["new"] += 1
            emit(
                "vacancy.ingested",
                {
                    "job_raw_id": job_raw_id,
                    "source": "hh",
                    "hh_vacancy_id": hh_id,
                    "pre_filtered": False,
                },
                actor="hh_ingest",
            )
        else:
            counts["duplicate"] += 1

    return counts
```

Commit: `feat(career_os): add HH ingest skill — store, prefilter, handler, normalization`

---

## Step 5: HH Ingest Worker

Create `capabilities/career_os/skills/vacancy_ingest_hh/worker.py`:

```python
"""Async background worker for HH.ru vacancy ingestion.

Polls HH API on configurable interval. Feeds vacancies into
the existing scoring → policy → approval pipeline.
"""

import asyncio
import logging

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.handler import (
    ingest_hh_vacancies,
    load_search_queries,
)
from connectors.hh_api import HHApiClient
from core.config import config
from core.events import emit

logger = logging.getLogger(__name__)


async def hh_ingest_worker() -> None:
    """Background worker: polls HH.ru API and ingests new vacancies.

    Runs in infinite loop. On each cycle:
    1. Load search queries from config.
    2. For each query: fetch vacancies from HH API.
    3. Normalize, dedup, pre-filter, save to job_raw.
    4. Emit hh.search_completed event with counts.
    5. Sleep for hh_poll_interval seconds.
    """
    if not config.hh_enabled:
        logger.info("HH ingest worker disabled (HH_ENABLED=false)")
        return

    interval = config.hh_poll_interval
    profile = Profile.from_file(config.profile_path)
    client = HHApiClient(
        user_agent=config.hh_user_agent,
        max_pages=config.hh_max_pages,
    )

    logger.info(
        "HH ingest worker started",
        extra={"interval": interval, "max_pages": config.hh_max_pages},
    )

    while True:
        try:
            queries = load_search_queries(config.hh_searches_path)
            if not queries:
                logger.warning("No HH search queries configured")
                await asyncio.sleep(interval)
                continue

            total_counts = {"total": 0, "new": 0, "duplicate": 0, "filtered": 0}

            for i, query_params in enumerate(queries):
                try:
                    logger.info(
                        "HH search %d/%d: %s",
                        i + 1,
                        len(queries),
                        query_params.get("text", "?"),
                    )
                    items = await client.search_vacancies(query_params)
                    counts = ingest_hh_vacancies(items, profile)

                    for key in total_counts:
                        total_counts[key] += counts[key]

                    logger.info(
                        "HH search %d complete: %d total, %d new, %d dup, %d filtered",
                        i + 1,
                        counts["total"],
                        counts["new"],
                        counts["duplicate"],
                        counts["filtered"],
                    )
                except Exception:
                    logger.exception(
                        "HH search %d failed",
                        i + 1,
                        extra={"query": query_params.get("text", "?")},
                    )

            emit(
                "hh.search_completed",
                total_counts,
                actor="hh_ingest",
            )

            logger.info(
                "HH ingest cycle complete: %d new, %d total",
                total_counts["new"],
                total_counts["total"],
            )

        except Exception:
            logger.exception("HH ingest worker cycle error")

        await asyncio.sleep(interval)
```

Commit: `feat(career_os): add HH ingest async worker`

---

## Step 6: Integrate into telegram_bot.py

Modify `connectors/telegram_bot.py`:

Add import:
```python
from capabilities.career_os.skills.vacancy_ingest_hh.worker import hh_ingest_worker
```

In `main()`, after `asyncio.create_task(scoring_worker(bot))`, add:
```python
    # Start HH ingest worker (if enabled)
    asyncio.create_task(hh_ingest_worker())
```

Commit: `feat(telegram): start HH ingest worker as background task`

---

## Step 7: Scoring Daily Cap (modify scoring worker)

Modify `capabilities/career_os/skills/match_scoring/worker.py`:

Add import:
```python
from capabilities.career_os.skills.vacancy_ingest_hh.store import get_today_scored_count
```

Inside the worker loop, BEFORE calling `score_vacancy_llm()`, add cap check:

```python
                    # Check scoring daily cap
                    if config.hh_scoring_daily_cap > 0:
                        with get_conn() as conn:
                            scored_today = get_today_scored_count(conn)
                        if scored_today >= config.hh_scoring_daily_cap:
                            logger.info(
                                "Scoring daily cap reached (%d/%d), skipping",
                                scored_today,
                                config.hh_scoring_daily_cap,
                            )
                            break  # exit the for-loop, will retry next cycle
```

Also add a one-time Telegram notification when cap is first hit in a cycle (similar to HOLD summary pattern):

```python
# After the for-loop, check if cap was reason for stopping
# (send notification once per day, track via event)
```

**Note:** The implementation should check for a `scoring.cap_reached` event today before sending the notification, same pattern as `was_hold_notification_sent_today()`.

Commit: `feat(scoring): add daily scoring cap enforcement`

---

## Step 8: Tests

### Create `tests/test_hh_api.py`

Test the HH API client (mock HTTP calls):

```python
# Test rate limiting (verify sleep called between requests)
# Test retry on 429 (verify exponential backoff)
# Test retry on 5xx
# Test pagination stops at max_pages
# Test empty results return empty list
# Test timeout handling
# Test successful single-page response
# Test successful multi-page response
```

Use `unittest.mock.patch` or `pytest-httpx` to mock httpx.

### Create `tests/test_hh_ingest.py`

Test the ingest handler + store:

```python
# Test normalize_vacancy extracts correct fields
# Test _strip_html removes tags
# Test save_hh_vacancy creates new record
# Test save_hh_vacancy returns existing on duplicate
# Test is_hh_vacancy_ingested returns False for new
# Test is_hh_vacancy_ingested returns True for existing
# Test ingest_hh_vacancies dedup counts
# Test ingest_hh_vacancies with pre-filtered vacancy
# Test load_search_queries from file
# Test load_search_queries missing file returns empty
# Test get_today_scored_count returns correct count
```

### Create `tests/test_hh_prefilter.py`

```python
# Test should_score returns True for clean vacancy
# Test should_score rejects negative signal (cold calling)
# Test should_score rejects excluded industry (gambling)
# Test should_score case insensitive
# Test should_score returns reason string on rejection
# Test should_score with empty profile signals passes all
```

Run all tests:
```bash
python3 -m pytest -q
# Expected: 130 existing + ~30 new = ~160 total, all green
```

Commit: `test: add HH connector, ingest, and prefilter tests`

---

## Step 9: Documentation

### Update `STATUS.md`
- PR-6: ✅ DONE
- Next: PR-7 (Data normalization)

### Update `CHANGELOG.md` — add PR-6 section:
- Added: HH.ru API connector with rate limiting and retry
- Added: HH ingest worker (async background poll)
- Added: Deterministic pre-filter (negative signals, excluded industries)
- Added: HH vacancy normalization (name, company, salary, requirements)
- Added: Cross-source dedup (hh_vacancy_id + canonical_key)
- Added: Scoring daily cap (configurable via HH_SCORING_DAILY_CAP)
- Added: Migration 006 (hh_vacancy_id column + index)
- Added: identity/hh_searches.example.json (search queries template)
- Changed: telegram_bot.py starts hh_ingest_worker
- Changed: scoring worker checks daily cap before LLM call

### Update `DECISIONS.md` — add PR-6 section:
- HH connector: Official API, anonymous access, no OAuth
- Search queries in identity/hh_searches.json (gitignored)
- Pre-filter: deterministic rejection of negative_signals and industries_excluded
- Scoring cap: default 100/day, prevents LLM cost runaway
- HH vacancies: source="hh", policy routes to AUTO_APPLY (not AUTO_QUEUE)
- Dedup: three levels — hh_vacancy_id, source_message_id UNIQUE index, canonical_key
- Rate limit: 1 req/sec to HH API, exponential backoff on 429

### Update `BACKLOG.md`
- PR-6: ✅ DONE
- Add PR-7: Data normalization (job_parsed)

### Update `docs/STATUS.md` (if exists)

Commit: `docs: update STATUS, CHANGELOG, DECISIONS, BACKLOG for PR-6`

---

## How to verify

```bash
# Tests
python3 -m pytest -q
# Expected: ~160 tests, all green

# Config check (HH disabled by default)
python -c "from core.config import config; print('HH enabled:', config.hh_enabled)"

# Migration check
python -c "from core.db import init_db; init_db(); print('OK')"

# Manual smoke test (requires real HH API access):
# 1. Create identity/hh_searches.json from example
# 2. Set HH_ENABLED=true in .env
# 3. python connectors/telegram_bot.py
# 4. Wait for first poll cycle (or set HH_POLL_INTERVAL=30 for testing)
# 5. Check Telegram for scoring notifications from HH vacancies
# 6. Check SQLite: SELECT COUNT(*) FROM job_raw WHERE source = 'hh';
# 7. Check events: SELECT * FROM events WHERE actor = 'hh_ingest';
```

---

## Final Report (write in Russian)

After all steps, generate a report:
1. Что реализовано
2. Какие файлы изменены/созданы
3. Результаты тестов (pytest output)
4. Подтверждение: policy rules не изменены
5. Подтверждение: HH_ENABLED=false по умолчанию (безопасный старт)
6. Количество HH-специфичных решений по безопасности
7. Список рисков или TODO для следующих PR
