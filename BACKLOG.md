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

### PR-3 Match Scoring (NEXT)
- match_scoring SKILL.md
- heuristic scorer 0..10 + reasons + extracted fields
- profile stored in memory/profile.json
- fixtures + unit tests

### PR-4 Apply Policy + Actions (NEXT)
- apply_policy SKILL.md
- daily limit (40 default), anti-duplicates policy
- write actions log (queued/auto/approved/rejected)

### PR-5 Telegram Approval UX (NEXT)
- approval queue in Telegram:
  - Approve / Reject / Snooze / Add note / Choose CV variant (later)
- operator commands:
  - /policy /limits /today /stats

### PR-6 HH Ingest v0.1 (NEXT)
Goal: minimal HH pipeline without manual browsing.
- connector that pulls from user-provided saved search URLs (or exported list)
- incremental updates (only new vacancies)
- normalization into job_raw with source="hh"
- dedup across sources (canonical_key/company+title heuristic)

Acceptance: “daily digest top-N HH vacancies + scoring” delivered via Telegram.

### PR-7 Data normalization (NEXT)
- introduce job_parsed table (role/company/geo/remote/salary/link)
- keep raw in job_raw, parsed in job_parsed

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
