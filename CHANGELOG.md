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
