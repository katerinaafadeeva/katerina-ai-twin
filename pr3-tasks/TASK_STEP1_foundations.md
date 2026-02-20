# TASK: PR-3 Step 1 — Migrations, Config, Security Baseline

## Role
You are the Implementation Agent (Tech Lead). Execute precisely.

## Context
We are building PR-3: LLM-Assisted Scoring for the katerina-ai-twin project.
This is Step 1 of 7: infrastructure foundation.
Branch: `pr3-assisted-scoring`

Read these files first to understand the current codebase:
- DECISIONS.md
- core/db.py
- core/events.py
- .env.example
- requirements.txt

## Deliverables

### 1. `core/config.py` — Config module

Create a config module. No Pydantic dependency for this — use a frozen dataclass.

```python
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    anthropic_api_key: str
    allowed_telegram_ids: List[int]
    profile_path: str
    log_level: str
    scoring_worker_interval: int  # seconds

    @classmethod
    def from_env(cls) -> "Config":
        ids_raw = os.getenv("ALLOWED_TELEGRAM_IDS", "")
        ids = [int(x.strip()) for x in ids_raw.split(",") if x.strip()]
        return cls(
            bot_token=os.environ["BOT_TOKEN"],
            db_path=os.getenv("DB_PATH", "data/career.db"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            allowed_telegram_ids=ids,
            profile_path=os.getenv("PROFILE_PATH", "identity/profile.json"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            scoring_worker_interval=int(os.getenv("SCORING_WORKER_INTERVAL", "10")),
        )

# Singleton — loaded once at import
config = Config.from_env()
```

### 2. `core/security.py` — Auth whitelist

```python
import logging
from aiogram.types import Message
from core.config import config

logger = logging.getLogger(__name__)

def is_authorized(message: Message) -> bool:
    """Check if Telegram user is in whitelist. Empty list = dev mode (allow all)."""
    if not config.allowed_telegram_ids:
        logger.warning("ALLOWED_TELEGRAM_IDS is empty — dev mode, all users allowed")
        return True
    return message.from_user is not None and message.from_user.id in config.allowed_telegram_ids
```

### 3. Migration system

Create `core/migrations/` directory with:

**`core/migrations/__init__.py`** — empty

**`core/migrations/migrate.py`** — migration runner:
- Creates `_migrations` tracking table
- Reads .sql files sorted by name
- Applies unapplied ones
- Logs each migration applied

**`core/migrations/001_initial.sql`** — extract EXACTLY the current DDL from `core/db.py`:
- job_raw, events, actions, policy tables
- idx_job_raw_dedup index
- Default policy seed

**`core/migrations/002_job_scores.sql`**:
```sql
CREATE TABLE IF NOT EXISTS job_scores (
    id              INTEGER PRIMARY KEY,
    job_raw_id      INTEGER NOT NULL REFERENCES job_raw(id),
    score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),
    reasons_json    TEXT NOT NULL,
    explanation     TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    profile_hash    TEXT NOT NULL,
    scorer_version  TEXT NOT NULL DEFAULT 'v1',
    scored_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_raw_id, scorer_version)
);
```

**`core/migrations/003_events_extend.sql`**:
```sql
ALTER TABLE events ADD COLUMN actor TEXT DEFAULT 'system';
ALTER TABLE events ADD COLUMN correlation_id TEXT;
```


### 4. Update `core/db.py`

- Remove inline DDL string
- `init_db()` now calls `migrate.apply_all(conn)`
- Keep `get_conn()` but add logging
- Add `get_conn_from_path(path)` for testing with :memory:

### 5. Update `core/events.py`

- Add `actor` and `correlation_id` parameters to `emit()`
- Default actor="system", correlation_id=None
- Both are optional for backward compatibility

### 6. Update `.env.example`

```
BOT_TOKEN=
DB_PATH=data/career.db
ANTHROPIC_API_KEY=
ALLOWED_TELEGRAM_IDS=
PROFILE_PATH=identity/profile.json
LOG_LEVEL=INFO
SCORING_WORKER_INTERVAL=10
```

### 7. Update `requirements.txt`

```
python-dotenv==1.0.1
aiogram>=3.0,<4
anthropic>=0.40.0
pydantic>=2.0,<3
pytest>=8.0
pytest-asyncio>=0.24
```

### 8. Update `.gitignore`

Add:
```
identity/
```

## Constraints

- Do NOT touch connectors/telegram_bot.py yet (that's Step 7)
- Do NOT create LLM client yet (that's Step 3)
- Do NOT create scoring logic yet (that's Step 4-5)
- Keep backward compatibility: existing code must still work
- Use `logging` module, not print()

## How to verify

```bash
python -c "from core.config import config; print('Config OK:', config.db_path)"
python -c "from core.db import init_db; init_db(); print('DB init OK')"
python -c "from core.events import emit; print('Events import OK')"
python -c "from core.security import is_authorized; print('Security import OK')"
```

## Commit message
```
feat(core): add migrations system, config module, security baseline

- core/config.py: frozen dataclass config from env
- core/security.py: Telegram auth whitelist
- core/migrations/: numbered SQL migration system
- 001: extract existing DDL
- 002: job_scores table
- 003: events actor/correlation_id
- policy defaults (threshold_low=5, threshold_high=7) already correct in 001_initial.sql
- Updated db.py to use migrations
- Updated events.py with actor/correlation_id
- Updated .env.example, .gitignore, requirements.txt
```
