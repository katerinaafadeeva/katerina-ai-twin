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
- `policy.hold_summary` event emitted when daily HOLD summary is sent
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

## PR-3: LLM-Assisted Scoring (2026-02-20)

### Added
- LLM-assisted vacancy scoring (0-10 scale) with Claude Haiku
- Async scoring worker (in-process, event-driven polling)
- Score persistence (job_scores table, idempotent INSERT OR IGNORE)
- LLM client abstraction with audit logging (tokens, cost, model)
- Input sanitization (zero-width chars, control chars, truncation)
- PII redaction for LLM calls (salary_signal only, no exact salary sent)
- Prompt injection defense (`<vacancy>` tags + NEVER-follow rule in system prompt)
- Pydantic validation for LLM outputs (score range, reasons, explanation length)
- Telegram auth whitelist (ALLOWED_TELEGRAM_IDS env var)
- Config module (core/config.py) with fail-fast on missing ANTHROPIC_API_KEY
- Migration system (numbered SQL files, _migrations tracking table)
- Profile model (identity/profile.json, gitignored; falls back to profile.example.json)
- Architecture Decision Records (ADR-001 through ADR-005)
- Engineering governance and security policies
- Test suite: 41 tests (schemas, sanitize, store, config)

### Changed
- Telegram bot: auth check on all handlers
- Telegram bot: scoring decoupled to worker (second message after save)
- Events: added actor and correlation_id fields (migration 003)

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
