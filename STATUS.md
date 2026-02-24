# Project Status

## Current state

| PR | Scope | Status |
|---|---|---|
| PR-1 | Initial bot skeleton (ingest, dedup, Telegram forward) | ✅ DONE |
| PR-2 | HH connector foundation | ✅ DONE |
| PR-3 | LLM-assisted scoring (config, migrations, LLM layer, worker, auth, tests) | ✅ DONE |
| PR-4 | Policy engine (threshold evaluation, daily cap, auto-queue) | ✅ DONE |
| PR-5 | Telegram Approval UX (inline keyboard, operator commands) | ✅ DONE |
| **PR-6** | **HH Ingest v0.1 (anonymous API, pre-filter, scoring cap, 70 new tests)** | **✅ DONE** |
| PR-7 | Data normalization (job_parsed table) | 🔜 NEXT |
| PR-8 | Cover letter generation (LLM, Playwright apply) | ⏳ planned |
| PR-9 | Web UI — pipeline dashboard | ⏳ planned |

## PR-6 summary (merged 2026-02-24)

- HH API: anonymous access, ≤1 req/sec rate limit, retry on 429/5xx, pagination
- Dedup: three levels — hh_vacancy_id (fast) → canonical_key (cross-source TG↔HH) → DB UNIQUE index
- Pre-filter: deterministic rejection by negative_signals + industries_excluded BEFORE LLM (saves tokens)
- Scoring daily cap: `HH_SCORING_DAILY_CAP=100`, emit-first durability (same pattern as HOLD)
- Worker: opt-in via `HH_ENABLED=true`, async background task
- Tests: **70 new tests, 200 total**, all green

## Next: PR-7 — Data Normalization

Goals:
- Introduce `job_parsed` table (role/company/geo/remote/salary/link)
- Keep raw text in `job_raw`, structured fields in `job_parsed`
- LLM-assisted extraction or heuristic parser for HH normalized fields

Depends on: PR-6 (hh_vacancy_id, normalized raw_text format)
