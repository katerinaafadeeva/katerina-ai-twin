# Project Status

## Current state

| PR | Scope | Status |
|---|---|---|
| PR-1 | Initial bot skeleton (ingest, dedup, Telegram forward) | ✅ DONE |
| PR-2 | HH connector foundation | ✅ DONE |
| **PR-3** | **LLM-assisted scoring (config, migrations, LLM layer, worker, auth, tests)** | **✅ DONE** |
| PR-4 | Policy engine (threshold evaluation, daily cap, auto-queue) | 🔜 NEXT |
| PR-5 | HH ingestion automation | ⏳ planned |
| PR-6 | Cover letter generation (LLM, approval flow) | ⏳ planned |
| PR-7 | Web UI — pipeline dashboard | ⏳ planned |

## PR-3 summary (merged 2026-02-20)

- Score contract: **0–10 INTEGER**, thresholds **5** (auto) / **7** (approval)
- LLM: Claude Haiku (default) → Sonnet (fallback on failure)
- Security: Telegram handler whitelist (`is_authorized`), prompt injection defence, PII redaction
- Worker: async in-process poll loop, not inline in Telegram handler
- Tests: **41 passed**, 0 failed

## Next: PR-4 — Policy Engine

Goals:
- Read `policy` table (threshold_low, threshold_high, daily_limit)
- Route scored vacancies: IGNORE / AUTO_QUEUE / APPROVAL_REQUIRED
- Enforce daily_limit counter
- Emit `vacancy.policy_applied` event
- Telegram notification includes action taken

Depends on: PR-3 (scoring worker, job_scores table)
