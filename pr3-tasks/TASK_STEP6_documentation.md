# TASK: PR-3 Step 6 — Documentation Update

## Role
You are the Implementation Agent. Final step.

## Deliverables

### 1. `STATUS.md` — Update

```markdown
# Status

## Date: 2026-02-20

### Done
- PR-1: SQLite foundation (job_raw/events/actions/policy) + init_db
- PR-2: Telegram ingest + dedup + event emission; tested end-to-end
- PR-3: LLM-assisted scoring (0-10) + async worker + security baseline + tests

### Next (execution order)
- PR-4: apply_policy (limits + anti-duplicates + actions log)
- PR-5: Telegram approval flow + operator commands
- PR-6: HH ingest v0.1 (saved search URLs -> job_raw -> digest)
- PR-7: Data normalization (job_parsed table)

### Notes
- Score contract: 0-10 INTEGER, display X/10. See ADR-001.
- LLM: Claude Haiku for scoring, audit logged. See ADR-002.
- Architecture docs in architecture/adr/ and architecture/governance/.
```

### 2. `DECISIONS.md` — Add entries

Add to end:

```markdown
## Score Contract (ADR-001)
- Range: 0-10 INTEGER (display as X/10 — no division)
- Thresholds: <5 ignore, 5-7 auto-queue, >7 approval required
- Boundaries: inclusive for auto (5 and 7 in auto range), >7 strict
- See architecture/adr/ADR-001-score-contract.md

## LLM-Assisted Scoring (ADR-002)
- Scoring is LLM-assisted from PR-3 (not heuristic-only)
- Model: Claude Haiku (cheapest), fallback to Sonnet
- Security: sanitization + PII redaction + prompt injection defense + audit
- See architecture/adr/ADR-002-llm-assisted-scoring.md

## Async Worker Pattern (ADR-003)
- Scoring runs in async background worker, not inline in Telegram handler
- Telegram responds immediately ("Сохранено"), score arrives as second message
- See architecture/adr/ADR-003-worker-architecture.md
```

### 3. `CHANGELOG.md` — Create

```markdown
# Changelog

## PR-3: LLM-Assisted Scoring (2026-02-20)

### Added
- LLM-assisted vacancy scoring (0-10 scale) with Claude Haiku
- Async scoring worker (in-process, event-driven polling)
- Score persistence (job_scores table, idempotent)
- LLM client abstraction with audit logging (tokens, cost, model)
- Input sanitization (zero-width chars, control chars, truncation)
- PII redaction for LLM calls (no exact salary sent)
- Prompt injection defense (data/instruction separation)
- Pydantic validation for LLM outputs
- Telegram auth whitelist (ALLOWED_TELEGRAM_IDS)
- Config module (core/config.py)
- Migration system (numbered SQL files)
- Profile model (identity/profile.json)
- Architecture Decision Records (ADR-001 through ADR-005)
- Engineering governance and security policies
- Test suite (pytest) with fixtures

### Changed
- Telegram bot: auth check on all handlers
- Telegram bot: scoring decoupled to worker (second message)
- Events: added actor and correlation_id fields
- Policy thresholds: defaults 5/7 (already correct in 001_initial.sql, no migration needed)

## PR-2: Telegram Ingest (2026-02-19)
- Telegram bot polling + vacancy_ingest_telegram
- Dedup (source, source_message_id)
- Event vacancy.ingested emitted

## PR-1: Foundation (2026-02-19)
- SQLite schema: job_raw/events/actions/policy
- init_db(), events emit
```

## Commit message
```
docs: update STATUS, DECISIONS, CHANGELOG for PR-3

- STATUS.md: PR-3 done, next steps updated
- DECISIONS.md: score contract, LLM-assisted, worker pattern
- CHANGELOG.md: created with full PR-3 changelog
```
