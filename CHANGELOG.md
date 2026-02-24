## PR-6: HH Ingest v0.1 (2026-02-24)

### Added
- `connectors/hh_api.py` — `HHApiClient`: async HTTP client, ≤1 req/sec rate limit, exponential backoff on 429/5xx, pagination up to `max_pages`, 30s timeout
- `core/migrations/006_job_raw_hh_id.sql` — non-destructive `ALTER TABLE job_raw ADD COLUMN hh_vacancy_id TEXT` + index
- `capabilities/career_os/skills/vacancy_ingest_hh/` — new skill:
  - `prefilter.py` — `should_score()`: deterministic rejection by `negative_signals` + `industries_excluded` (case-insensitive substring, no LLM)
  - `store.py` — `compute_canonical_key` (SHA256 16-char hex, identical algorithm to TG ingest), `is_hh_vacancy_ingested`, `is_canonical_key_ingested`, `get_today_scored_count`, `was_scoring_cap_notification_sent_today`, `save_hh_vacancy`
  - `handler.py` — `load_search_queries`, `normalize_vacancy` (name/employer/salary/area/schedule/snippet → raw_text), `ingest_hh_vacancies` (3-level dedup pipeline)
  - `worker.py` — `hh_ingest_worker()`: async background loop, no-op if `HH_ENABLED=false`, emits `hh.search_completed` per query
  - `SKILL.md` — skill contract
- `identity/hh_searches.example.json` — example search queries (no personal data)
- 6 new config fields: `hh_enabled`, `hh_poll_interval`, `hh_user_agent`, `hh_max_pages`, `hh_scoring_daily_cap`, `hh_searches_path`
- **70 new tests** (test_hh_api.py: 16, test_hh_ingest.py: 40, test_hh_prefilter.py: 10, test_hh_ingest.py scoring cap: 5); **200 total**

### Changed
- `match_scoring/worker.py` — added scoring daily cap check before `score_vacancy_llm()` call; cap notification (`scoring.cap_reached` event + Telegram message) with emit-first durability pattern
- `connectors/telegram_bot.py` — registered `hh_ingest_worker` as background asyncio task
- `.env.example` — added HH-related env vars with safe defaults (`HH_ENABLED=false`)
- `requirements.txt` — added `httpx`

### Dedup contract (3 levels)

| Level | Key | Scope |
|---|---|---|
| 1 | `hh_vacancy_id` | HH source only — fast O(1) index lookup |
| 2 | `canonical_key` | All sources — catches TG↔HH cross-source duplicates |
| 3 | DB UNIQUE `(source, source_message_id)` | Last-resort — INSERT OR IGNORE |

### New events

| Event | Actor | Payload |
|---|---|---|
| `vacancy.ingested` | `hh_ingest` | job_raw_id, source="hh", hh_vacancy_id |
| `hh.search_completed` | `hh_ingest_worker` | query_text, total, new, duplicate, filtered |
| `scoring.cap_reached` | `scoring_worker` | cap |

---

## PR-5: Telegram Approval UX + Operator Commands (2026-02-20)

### Added
- Inline keyboard (approve/reject/snooze) for APPROVAL_REQUIRED notifications
- /today command — daily summary: ingested, scored, by action_type, by status, limit usage
- /limits command — policy thresholds and remaining daily capacity
- /stats command — /today summary + list of pending APPROVAL_REQUIRED actions
- Action state transitions: pending → approved / rejected / snoozed (idempotent guard via WHERE status='pending' + rowcount check)
- Migration 005: non-destructive ALTER TABLE actions ADD COLUMN updated_at TIMESTAMP
- control_plane skill: store.py (5 query functions) + handlers.py (callback + 3 commands)
- Authorization: is_callback_authorized() for CallbackQuery, is_authorized() for all commands
- Events emitted on approval: vacancy.approved / vacancy.rejected / vacancy.snoozed
- 35 new tests (test_control_plane_store.py, test_control_plane_handlers.py); 130 total

### Changed
- worker.py APPROVAL_REQUIRED notification: now includes InlineKeyboardMarkup; action_rowid captured from save_action()
- connectors/telegram_bot.py: registered cmd_today, cmd_limits, cmd_stats, handle_approval_callback
- tests/conftest.py: added os.environ.setdefault for BOT_TOKEN and ANTHROPIC_API_KEY (test dummies) to enable handlers.py import in unit tests

---

# Changelog

## PR-4: Apply Policy Engine (2026-02-20)

### Added
- Deterministic policy engine (`apply_policy` skill): IGNORE / AUTO_QUEUE / AUTO_APPLY / HOLD / APPROVAL_REQUIRED
- Source-aware routing: hh source → AUTO_APPLY; other sources → AUTO_QUEUE
- Daily limit counter (counts AUTO_QUEUE + AUTO_APPLY both, not only one type)
- HOLD daily summary notification — one per UTC day, not per-vacancy
- `save_action()` — persists policy decision to actions table with score, reason, actor, correlation_id
- `get_policy()` — reads policy row with safe defaults (5/7/40)
- `was_hold_notification_sent_today()` — deduplicates HOLD summary via events table
- `vacancy.policy_applied` event emitted after each policy decision
- `policy.hold_summary` event emitted when daily HOLD summary is sent (emit before send_message for durability)
- Migration 004: non-destructive ALTER TABLE actions (adds score, reason, actor, correlation_id)
- 54 new tests (test_policy_engine.py, test_policy_store.py); 95 total

### Changed
- `scoring_worker`: old generic notification replaced with policy-based routing
  - IGNORE: silent (no Telegram message)
  - AUTO_APPLY: notification with HH auto-apply confirmation
  - AUTO_QUEUE: notification with queue position
  - APPROVAL_REQUIRED: notification with approval request + explanation
  - HOLD: no per-vacancy notification; daily summary after worker cycle

---

## PR-3 — LLM-Assisted Vacancy Scoring (2026-02-20)

### Added

**Infrastructure**
- `core/config.py` — frozen dataclass Config; loads from `.env`; fail-fast on missing `BOT_TOKEN` / `ANTHROPIC_API_KEY`
- `core/security.py` — `is_authorized()` whitelist check for all Telegram handlers
- `core/migrations/` — numbered SQL migration runner; migrations 001 (initial schema), 002 (job_scores), 003 (events extension)
- `core/events.py` — extended with `actor` and `correlation_id` params for full audit traceability

**LLM Layer**
- `core/llm/client.py` — async Anthropic API wrapper; emits `llm.call` audit event with tokens/cost/duration per call
- `core/llm/sanitize.py` — vacancy text sanitization (zero-width chars, control chars, truncation); profile PII redaction (exact salary → `salary_signal`)
- `core/llm/schemas.py` — Pydantic validation: `ScoringOutput` (score 0–10, reasons, explanation), `LLMCallRecord`
- `core/llm/prompts/scoring_v1.py` — structured scoring prompt with prompt injection defence (`<vacancy>` tags + NEVER-follow-instructions rule)

**Career OS — Match Scoring Skill**
- `capabilities/career_os/models.py` — frozen `Profile` dataclass; `from_file()` with fallback to `profile.example.json`; `content_hash()` for cache invalidation
- `capabilities/career_os/skills/match_scoring/handler.py` — pure async `score_vacancy_llm()`; primary Haiku → fallback Sonnet on failure
- `capabilities/career_os/skills/match_scoring/store.py` — `get_unscored_vacancies()` (LEFT JOIN), `save_score()` (INSERT OR IGNORE, idempotent), `get_score()`
- `capabilities/career_os/skills/match_scoring/worker.py` — async background worker; polls unscored vacancies; persists scores; emits `vacancy.scored`; sends Telegram notification
- `capabilities/career_os/skills/match_scoring/SKILL.md` — skill contract

**Identity**
- `identity/profile.example.json` — template profile (no personal data committed)

**Tests — 41 passed**
- `tests/conftest.py` — in-memory SQLite fixture with full migration stack; shared Profile and ScoringOutput fixtures
- `tests/test_schemas.py` — ScoringOutput validation: score range, reasons, explanation length
- `tests/test_sanitize.py` — sanitization pipeline + PII redaction + injection fixture
- `tests/test_store.py` — idempotency, unscored query, scorer_version isolation, get_score
- `tests/test_config.py` — env parsing, ALLOWED_TELEGRAM_IDS variants, fail-fast on missing key

### Changed

- `connectors/telegram_bot.py` — added `is_authorized()` to all handlers; `scoring_worker` started as `asyncio.create_task`
- `.env.example` — added `ANTHROPIC_API_KEY`, `ALLOWED_TELEGRAM_IDS`, `PROFILE_PATH`, `LOG_LEVEL`, `SCORING_WORKER_INTERVAL`
- `requirements.txt` — added `pydantic`, `anthropic`, `pytest`, `pytest-asyncio`

### Score Contract

| Parameter | Value |
|---|---|
| Range | 0–10 (INTEGER) |
| Storage | `job_scores.score INTEGER CHECK(BETWEEN 0 AND 10)` |
| Threshold low | 5 (auto-queue/apply) |
| Threshold high | 7 (approval required, 7 included) |
| Emojis | 🟢 ≥7 · 🟡 5–6 · 🔴 <5 |

### Audit Events

| Event | Actor | Payload |
|---|---|---|
| `vacancy.ingested` | `telegram_forward` | job_raw_id, is_new |
| `vacancy.scored` | `scoring_worker` | job_raw_id, score |
| `llm.call` | `scoring_worker` | model, prompt_version, tokens, cost_usd, duration_ms, success |

---

## PR-2: Telegram Ingest (2026-02-19)

### Added
- Telegram bot polling + vacancy_ingest_telegram skill
- Dedup by (source, source_message_id)
- `vacancy.ingested` event emitted on each new vacancy

---

## PR-1: Foundation (2026-02-19)

### Added
- SQLite schema: job_raw / events / actions / policy tables
- `init_db()` with migration runner
- `.env.example`, `.gitignore` (secrets + db)
