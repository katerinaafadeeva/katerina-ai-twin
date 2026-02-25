# Backlog — Katerina AI Twin

## North Star
Minimize cognitive load and maximize relevance: user sees only high-quality opportunities and spends time on approvals and interviews, not browsing.

---

## Milestone M0 — Foundation + First Data Loop (DONE / IN PROGRESS)
### PR-1 Foundation (DONE)
- SQLite schema: job_raw/events/actions/policy
- init_db(), events emit
- env pattern (.env.example), ignore secrets & db

### PR-2 Telegram Ingest (DONE)
- Telegram bot polling + vacancy_ingest_telegram
- dedup (source, source_message_id)
- event vacancy.ingested emitted
- RU confirmations

---

## Milestone M1 — Unified Career Pipeline (Telegram control, multi-source data)
Goal: HH + TG feed into one pipeline with scoring, policy and approvals.

### PR-3 Match Scoring (DONE)
- LLM-assisted scoring 0-10 (Claude Haiku) + async worker + 41 tests
- Security: sanitization, PII redaction, prompt injection defense, Pydantic validation
- Config module, migration system, profile model (profile.example.json)

### PR-4 Apply Policy + Actions (DONE)
- Deterministic policy engine: IGNORE/AUTO_QUEUE/AUTO_APPLY/HOLD/APPROVAL_REQUIRED
- Daily limit (40 default), counts AUTO_QUEUE + AUTO_APPLY both
- Actions log with score/reason/actor/correlation_id (migration 004)
- HOLD daily summary notification (once per UTC day)
- 54 new tests (95 total)

### PR-5 Telegram Approval UX (DONE)
- Inline keyboard approve/reject/snooze for APPROVAL_REQUIRED notifications
- /today, /limits, /stats operator commands
- Action state transitions with idempotent guard
- 35 new tests (130 total)

### PR-6 HH Ingest v0.1 (DONE)
- Anonymous HH API (≤1 req/sec, retry on 429/5xx, pagination up to max_pages)
- Migration 006: hh_vacancy_id column + index on job_raw
- connectors/hh_api.py: HHApiClient with rate limiting and exponential backoff
- vacancy_ingest_hh skill: prefilter, store (3-level dedup), handler, background worker
- Scoring daily cap: HH_SCORING_DAILY_CAP=100, enforced before LLM call
- Pre-filtered vacancies NOT saved to job_raw (no spurious scoring)
- 70 new tests (200 total)

### PR-7 Cover Letter Generation (DONE)
- Migration 007: cover_letters table with UNIQUE(job_raw_id, action_id), tokens, cost, is_fallback
- Generator: Claude Haiku 4.5, temperature=0.3; prompt injection defence via XML tags
- Fallback chain: real file → .example.txt → hardcoded default (never blocks)
- Daily cap (COVER_LETTER_DAILY_CAP=50), emit-first cap notification
- Worker integration: AUTO_APPLY + APPROVAL_REQUIRED, non-fatal try/except
- 40 new tests (240 total)

### PR-8 Data normalization (NEXT)
- introduce job_parsed table (role/company/geo/remote/salary/link)
- keep raw in job_raw, parsed in job_parsed
- heuristic or LLM-assisted extraction of structured fields from normalized raw_text

---

## Milestone M2 — Web UI Analytics (Workspace Plane)
Goal: dashboards & weekly review.
- pipeline board (ingested/scored/auto/approved/applied/interview/offer)
- charts: source breakdown, conversion, time-to-response
- market insights: keywords/skills frequency & trends
- CV gap report + learning recommendations

---

## Milestone M3 — Expand to Twin OS (after Career OS stable)
- comms_os: email/DM follow-ups (Gmail later), templates, reminders
- ops_os: calendar sync, daily plan, reminders
- learning_os: track course progress + map to market gaps
- finance_os: optional routines/alerts

---

## Operating rules
- 1 PR = 1 logical change
- smallest possible diffs
- decisions captured in DECISIONS.md (not only in chat)
- token budget policy enforced
BACKLOG — Post PR-4 follow-ups (не блокеры)

Timezone-aware daily windows
Сейчас date('now') = UTC. Для локального дня пользователя сделать TZ-aware (config-based).

Daily limit under concurrency (future multi-worker)
Возможен TOCTOU race между get_today_auto_count и save_action при >1 инстансе воркера.
Решение: lock/transaction/atomic insert strategy.

Telegram rate limiting / throttling (актуально с PR-6 HH ingest)
При burst вакансий добавить небольшой sleep/очередь отправки сообщений.

Optional: audit IGNORE decisions for analytics
Сейчас IGNORE не пишется в actions (silent). Для аналитики можно добавить отдельную запись без уведомлений.

Retention / cleanup policy for events/actions/job_raw
База будет расти; добавить периодическую очистку/архивацию (M2).