# Project Status

## Current state

| PR | Scope | Status |
|---|---|---|
| PR-1 | Initial bot skeleton (ingest, dedup, Telegram forward) | ✅ DONE |
| PR-2 | HH connector foundation | ✅ DONE |
| PR-3 | LLM-assisted scoring (config, migrations, LLM layer, worker, auth, tests) | ✅ DONE |
| PR-4 | Policy engine (threshold evaluation, daily cap, auto-queue) | ✅ DONE |
| PR-5 | Telegram Approval UX (inline keyboard, operator commands) | ✅ DONE |
| PR-6 | HH Ingest v0.1 (anonymous API, pre-filter, scoring cap, 70 new tests) | ✅ DONE |
| PR-7 | Cover letter generation (LLM + fallback, daily cap, 40 new tests) | ✅ DONE |
| **PR-8** | **Playwright auto-apply on HH.ru (browser automation, 49 new tests)** | **✅ DONE** |

## 🎉 MVP v1 COMPLETE — PR-1..PR-8 merged

End-to-end pipeline:
**HH Ingest → Scoring → Policy → Cover Letter → Auto-Apply → ✅**

## PR-6 summary (merged 2026-02-24)

- HH API: anonymous access, ≤1 req/sec rate limit, retry on 429/5xx, pagination
- Dedup: three levels — hh_vacancy_id (fast) → canonical_key (cross-source TG↔HH) → DB UNIQUE index
- Pre-filter: deterministic rejection by negative_signals + industries_excluded BEFORE LLM (saves tokens)
- Scoring daily cap: `HH_SCORING_DAILY_CAP=100`, emit-first durability (same pattern as HOLD)
- Worker: opt-in via `HH_ENABLED=true`, async background task
- Tests: **70 new tests, 200 total**, all green

## PR-7 summary (merged 2026-02-24)

- `cover_letters` table (migration 007): UNIQUE(job_raw_id, action_id), tokens, cost, is_fallback
- Generator: Claude Haiku 4.5, temperature=0.3, 150–400 words in Russian; fallback on any LLM failure
- Fallback chain: real file → `.example.txt` sibling → hardcoded default (never blocks)
- Daily cap: `COVER_LETTER_DAILY_CAP=50`, excludes fallbacks from count, emit-first notification
- Worker integration: cover letter generated for AUTO_APPLY + APPROVAL_REQUIRED (non-fatal try/except)
- APPROVAL_REQUIRED notification: shows first 200 chars of cover letter as preview
- Tests: **40 new tests, 240 total**, all green

## PR-8 summary (2026-02-26)

- Migration 008: `apply_runs` table — execution log separate from `actions` decision log. `UNIQUE(action_id, attempt)`, indexes on `action_id` / `status` / `finished_at`.
- `connectors/hh_browser/`: `client.py` (lazy Playwright, auth storage state), `selectors.py`, `apply_flow.py` (DONE/ALREADY_APPLIED/MANUAL_REQUIRED/CAPTCHA/SESSION_EXPIRED/FAILED), `bootstrap.py`
- `capabilities/career_os/skills/hh_apply/`: `store.py` (`save_apply_run`, attempt model, queue filter with no-duplicate-apply guarantee), `worker.py`, `notifier.py`, `SKILL.md`
- Feature flag: `HH_APPLY_ENABLED=false` (safe opt-in). Daily cap `APPLY_DAILY_CAP=10`. Random delays `[10..30]s`. Batch size 5. Max 3 attempts per task.
- Captcha → stop batch. Session expired → stop + notify. All browser ops in try/except.
- `/resume_apply` Telegram command. Emit-first apply cap notification.
- Tests: **49 new tests, 293 total**, all green. Zero LLM calls. Zero real Playwright in tests.

## Iteration 2 — Post-MVP Roadmap

| PR | Scope |
|---|---|
| PR-9 | Data normalization (job_parsed table) |
| PR-10 | Web UI — pipeline dashboard |
| PR-11 | comms_os — email/DM follow-ups |
| PR-12 | Auto-retry with backoff, screenshots on error, Docker support |
