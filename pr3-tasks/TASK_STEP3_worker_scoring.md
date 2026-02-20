# TASK: PR-3 Step 3 — Scoring Worker + Scoring Skill + Profile Model

## Role
You are the Implementation Agent (Tech Lead). Execute precisely.

## Context
PR-3, Step 3 of 7. Steps 1-2 (foundations + LLM client) are complete.
Now we build the scoring worker and the skill itself.

Read first:
- core/llm/client.py (LLM abstraction)
- core/llm/schemas.py (output schemas)
- core/llm/prompts/scoring_v1.py (prompt)
- core/llm/sanitize.py (sanitization)
- core/config.py (config)
- core/db.py (database)
- architecture/adr/ADR-001-score-contract.md
- architecture/adr/ADR-003-worker-architecture.md

## Deliverables

### 1. `capabilities/career_os/models.py` — Profile model

Frozen dataclass. Loads from JSON file.

Fields: target_roles, target_seniority, work_format, geo_cities, relocation (bool), salary_min (int), salary_currency, required_skills, bonus_skills, negative_signals, industries_preferred, industries_excluded, languages.

Methods:
- `from_file(path: str) -> Profile` — loads from JSON
- `content_hash() -> str` — SHA256[:16] of deterministic serialization (for cache invalidation)

### 2. `identity/profile.json` — Template profile

Create with placeholder structure. Katerina will fill real values.

```json
{
  "version": "1.0",
  "updated_at": "2026-02-20",
  "target_roles": ["Product Manager", "Product Owner", "Business Development Manager"],
  "target_seniority": ["middle", "senior"],
  "work_format": ["remote", "hybrid"],
  "geo_preferences": {
    "cities": ["Москва", "remote"],
    "relocation": false
  },
  "salary": {
    "min": 250000,
    "currency": "RUB"
  },
  "required_skills": ["product management", "analytics", "stakeholder management", "roadmap"],
  "bonus_skills": ["SQL", "Jira", "Figma", "Python", "data analysis"],
  "negative_signals": ["cold calling", "MLM", "network marketing", "unpaid internship", "бесплатная стажировка"],
  "industries_preferred": ["tech", "fintech", "edtech", "SaaS"],
  "industries_excluded": ["gambling", "tobacco", "adult"],
  "languages": ["Russian", "English"]
}
```

### 3. `capabilities/career_os/skills/match_scoring/SKILL.md`

```markdown
---
name: match_scoring
description: LLM-assisted vacancy scoring with structured output
---

# Match Scoring (v1 — LLM-Assisted)

## Input
- job_raw record (raw_text, id)
- Profile (from identity/profile.json)

## Output
- score: 0–10 (INTEGER)
- reasons: [{criterion, matched, note}]
- explanation: 1-2 sentences in Russian

## Flow
1. Worker picks up unscored vacancy (event-driven poll)
2. Sanitize vacancy text (remove injection vectors, truncate)
3. Prepare profile (redact PII — no exact salary)
4. Call LLM (Claude Haiku, temperature=0, structured JSON output)
5. Validate response (Pydantic schema)
6. Persist to job_scores (idempotent: UNIQUE on job_raw_id + scorer_version)
7. Emit vacancy.scored event
8. Notify user via Telegram (second message)

## Idempotency
- Same job_raw_id + same scorer_version → no re-scoring
- Worker checks before calling LLM

## Error handling
- LLM failure → log + skip + retry on next cycle
- Validation failure → retry once with fallback model → skip + log
```

### 4. `capabilities/career_os/skills/match_scoring/__init__.py` — empty

### 5. `capabilities/career_os/skills/match_scoring/store.py` — Score persistence

Functions:

**`get_unscored_vacancies(conn, scorer_version="v1") -> List[dict]`**
```sql
SELECT jr.id, jr.raw_text, jr.source, jr.created_at
FROM job_raw jr
LEFT JOIN job_scores js ON jr.id = js.job_raw_id AND js.scorer_version = ?
WHERE js.id IS NULL
ORDER BY jr.created_at ASC
```

**`save_score(conn, job_raw_id, result: ScoringOutput, profile_hash, model, prompt_version, input_tokens, output_tokens, cost_usd) -> int`**
- INSERT OR IGNORE (idempotent — if already scored with this version, skip)
- Returns rowid or 0 if skipped

**`get_score(conn, job_raw_id, scorer_version="v1") -> Optional[dict]`**
- Returns score record or None

### 6. `capabilities/career_os/skills/match_scoring/handler.py` — Scoring orchestration

Main function:

**`async def score_vacancy_llm(vacancy_text: str, vacancy_id: int, profile: Profile, correlation_id: str) -> ScoringOutput`**

Flow:
1. `sanitize_for_llm(vacancy_text)`
2. `prepare_profile_for_llm(profile)`
3. Build user message from `USER_TEMPLATE`
4. Call `call_llm_scoring(SYSTEM_PROMPT, user_message, PROMPT_VERSION, vacancy_id, correlation_id)`
5. If fails → retry once with `FALLBACK_MODEL`
6. Return `ScoringOutput`

### 7. `capabilities/career_os/skills/match_scoring/worker.py` — Async worker loop

```python
import asyncio
import logging
from uuid import uuid4

from aiogram import Bot

from core.config import config
from core.db import get_conn
from core.events import emit
from capabilities.career_os.models import Profile
from capabilities.career_os.skills.match_scoring.handler import score_vacancy_llm
from capabilities.career_os.skills.match_scoring.store import get_unscored_vacancies, save_score

logger = logging.getLogger(__name__)


def _score_emoji(score: int) -> str:
    if score >= 7:
        return "🟢"
    elif score >= 5:
        return "🟡"
    return "🔴"


async def scoring_worker(bot: Bot) -> None:
    """Background worker: polls for unscored vacancies and scores them via LLM."""
    profile = Profile.from_file(config.profile_path)
    interval = config.scoring_worker_interval
    logger.info("Scoring worker started", extra={"interval": interval})

    while True:
        try:
            with get_conn() as conn:
                unscored = get_unscored_vacancies(conn)

            for vacancy in unscored:
                correlation_id = str(uuid4())
                job_raw_id = vacancy["id"]
                try:
                    result = await score_vacancy_llm(
                        vacancy_text=vacancy["raw_text"],
                        vacancy_id=job_raw_id,
                        profile=profile,
                        correlation_id=correlation_id,
                    )

                    with get_conn() as conn:
                        save_score(
                            conn, job_raw_id, result,
                            profile_hash=profile.content_hash(),
                            model="logged_in_llm_call",  # actual model logged in llm.call event
                            prompt_version="scoring_v1",
                            input_tokens=0,  # tracked in llm.call event
                            output_tokens=0,
                            cost_usd=0.0,
                        )

                    emit("vacancy.scored", {
                        "job_raw_id": job_raw_id,
                        "score": result.score,
                    }, actor="scoring_worker", correlation_id=correlation_id)

                    # Notify via Telegram
                    # Get chat_id from config (single user for now)
                    if config.allowed_telegram_ids:
                        chat_id = config.allowed_telegram_ids[0]
                        emoji = _score_emoji(result.score)
                        await bot.send_message(
                            chat_id,
                            f"Оценка #{job_raw_id}: {emoji} {result.score}/10\n{result.explanation}"
                        )

                except Exception:
                    logger.exception("Scoring failed for vacancy",
                                   extra={"job_raw_id": job_raw_id})

        except Exception:
            logger.exception("Worker loop error")

        await asyncio.sleep(interval)
```

## Constraints

- Do NOT modify telegram_bot.py yet (Step 7)
- handler.py must be a pure async function (no DB access — that's worker's job)
- store.py functions accept `conn` as parameter (no get_conn() inside)
- All functions: type hints + docstrings
- Use `logging`

## How to verify

```bash
python -c "from capabilities.career_os.models import Profile; p = Profile.from_file('identity/profile.json'); print(p.target_roles, p.content_hash())"
python -c "from capabilities.career_os.skills.match_scoring.store import get_unscored_vacancies; print('Store import OK')"
```

## Commit message
```
feat(career_os): add scoring worker, skill handler, profile model, and persistence

- capabilities/career_os/models.py: Profile dataclass with from_file + content_hash
- identity/profile.json: template profile for Katerina
- match_scoring/worker.py: async background worker with polling + notifications
- match_scoring/handler.py: LLM scoring orchestration with retry
- match_scoring/store.py: idempotent score persistence + unscored query
- match_scoring/SKILL.md: skill contract
```
