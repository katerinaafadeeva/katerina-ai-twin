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
| **PR-7** | **Cover letter generation (LLM + fallback, daily cap, 40 new tests)** | **✅ DONE** |
| PR-8 | Data normalization (job_parsed table) | 🔜 NEXT |
| PR-9 | Web UI — pipeline dashboard | ⏳ planned |
| PR-9 | Web UI — pipeline dashboard | ⏳ planned |

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

## Next: PR-8 — Data Normalization

Goals:
- Introduce `job_parsed` table (role/company/geo/remote/salary/link)
- Keep raw text in `job_raw`, structured fields in `job_parsed`
- LLM-assisted extraction or heuristic parser for HH normalized fields

Depends on: PR-6 (hh_vacancy_id, normalized raw_text format), PR-7 (cover_letters table)
