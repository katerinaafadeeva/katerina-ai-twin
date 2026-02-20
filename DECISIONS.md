# Decisions — Katerina AI Twin

## Product Vision
Katerina AI Twin is a personal operating system (Twin OS) that incrementally automates:
1) Career search & applications (Career OS)
2) Communications (follow-ups, emails, templates)
3) Calendar & daily planning
4) Learning & skill-gap analytics (market vs CV vs learning plan)
User manages a hybrid team: AI agents + human operator, with strict cost (tokens/time) controls.

## Planes (Interaction Model)
- Control Plane (Telegram-first): fast commands, approvals, notifications.
- Workspace Plane (Web UI): dashboards, pipeline, analytics, policy settings, audits.
- Data Plane (Connectors): HH.ru, Telegram channels, (later) LinkedIn, email, calendar.
Telegram is NOT a source of truth; it is an operator interface.

## Architecture Principles
- Capability-driven: capabilities/{career_os, ops_os, comms_os, learning_os, finance_os...}
- Skills are modular intelligence units with contracts (SKILL.md).
- Start as modular monolith for speed and low ops overhead.
- Scale by connectors + clear interfaces; microservices only when there is real load/need.
- "Policy as data": rules configurable without code deploy.
- Auditability: every decision logged (actions), every ingest logged (events).

## Data & Memory Model (v0.x)
System of record: SQLite (local).
Tables (minimum): job_raw, events, actions, policy, (later) job_parsed, companies, contacts, conversations.
Identity Pack (versioned files + pointers):
- target roles & geo prefs
- CV variants (PM/BD/Product)
- communication style (tone, do/don’t)
- constraints (salary floor, remote/hybrid, relocation)
Secrets never committed (.env ignored).

## Sources & Ingestion Strategy
We support multiple sources. Implementation is phased:
- v0.1: Telegram forward + minimal HH ingestion (semi-automatic)
- v0.2: HH ingestion automation (safe, rate-limited) + TG channel ingest improvements
- v1.0: unify all sources into a single pipeline + full analytics UI

### HH.ru
Primary funnel source.
Ingestion approach must be realistic and maintainable:
- v0.1: user provides HH search URLs (saved queries). System fetches/updates via connector (method TBD).
- v0.2+: full automation with caching, dedup, and incremental updates.
(We will decide exact technical method after reviewing HH constraints; prefer low-risk compliant approach.)

### Telegram channels
Secondary source; two modes:
- v0.1: forward posts manually to the bot (already implemented)
- v0.2+: optional direct ingestion:
  - prefer Bot API compliant options first
  - if insufficient: isolated MTProto connector (Telethon userbot) with explicit risk controls

## Core Career Loop (v0.x)
ingest (HH/TG/other) -> normalize -> dedup -> score (0..10) -> apply_policy -> queue actions -> notify/approve -> log outcome

## Scoring & Policy (Career OS)
Score scale: 0..10.
- score < 5: IGNORE (silent, no notification)
- score 5-6, source=hh, within limit: AUTO_APPLY
- score 5-6, other source, within limit: AUTO_QUEUE
- score 5-6, daily limit reached: HOLD (one summary notification/day)
- score >= 7 (7 included): APPROVAL_REQUIRED (never blocked by daily limit)
Guardrails:
- daily auto-send limit: default 40 (counts AUTO_QUEUE + AUTO_APPLY both)
- anti-duplicates: do not apply twice to same company/role; do not ingest duplicates

## Analytics Requirements (Web UI)
Must support daily/weekly decision-making:
- funnel: ingested -> scored -> auto -> approved -> applied -> interviews -> offers
- source breakdown: HH vs TG
- market insights: top required skills/keywords, role distribution, geo/remote stats
- CV & learning insights: gaps between market requirements and CV/learning plan
Analytics computed locally from SQLite (v0.x), UI later.

## Language
User-facing: Russian.
Internal code/identifiers/DB: English.

## Cost Controls (Token Budget)
- No LLM for deterministic parts: ingestion, dedup, policy, counters.
- LLM allowed for:
  - vacancy scoring (Claude Haiku, audit logged) — approved since PR-3
  - cover letters for score >= 7 — planned PR-5
  - aggregated weekly market analysis (sampled data) — Milestone M2
- Caching and minimal context injection mandatory.

## PR-3 Decisions (LLM-Assisted Scoring)
- Score contract: 0-10 INTEGER (display as X/10). Stored in job_scores. See ADR-001.
- LLM model: Claude Haiku (cheapest), fallback to Sonnet. See ADR-002.
- Security: sanitization + PII redaction + prompt injection defense + Pydantic validation.
- Worker pattern: async background task, not inline in Telegram handler. See ADR-003.
- Profile: identity/profile.json (gitignored); falls back to profile.example.json with WARNING.

## PR-4 Decisions (Policy Engine)
- Action types (Founder contract):
  - IGNORE: score < 5 — silent, no notification
  - AUTO_QUEUE: score 5-6, non-hh source, within daily limit
  - AUTO_APPLY: score 5-6, source='hh', within daily limit
  - HOLD: score 5-6, daily limit reached — one summary notification/day, not per-vacancy
  - APPROVAL_REQUIRED: score >= 7 (7 included, not only 8+) — never blocked by daily limit
- Daily limit counts AUTO_QUEUE + AUTO_APPLY both (not only AUTO_APPLY).
- Policy engine is inline in scoring worker (not a separate asyncio task): deterministic, <1ms.
- HOLD summary: tracked via policy.hold_summary event in events table, sent once per UTC day.
- Migration 004: ALTER TABLE only (non-destructive), adds score/reason/actor/correlation_id to actions.
