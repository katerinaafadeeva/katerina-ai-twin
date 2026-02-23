# Status

## Date: 2026-02-20

### Done
- PR-1: SQLite foundation (job_raw/events/actions/policy) + init_db
- PR-2: Telegram ingest + dedup + event emission; tested end-to-end
- PR-3: LLM-assisted scoring (0-10) + async worker + security baseline + 41 tests
- PR-4: apply_policy (deterministic routing + actions log + daily limit + HOLD summary) + 54 tests
- PR-5: Telegram approval UX (inline keyboard, /today /limits /stats, action state transitions) + 35 tests

### Next (execution order)
- PR-6: HH ingest v0.1 (saved search URLs -> job_raw -> digest)
- PR-7: Data normalization (job_parsed table)

### Notes
- Score contract: 0-10 INTEGER. Thresholds: <5 IGNORE, 5-6 AUTO_QUEUE/AUTO_APPLY, >=7 APPROVAL_REQUIRED. See ADR-001.
- LLM: Claude Haiku for scoring, audit logged. See ADR-002.
- Policy engine: deterministic, no LLM, inline in scoring worker.
- Telegram is control plane; HH is primary funnel source in roadmap.
