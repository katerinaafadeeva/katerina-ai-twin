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

## PR-3 Decisions (2026-02-20)

### Scoring scale: 0–10 (not 0–100)
Score is stored and displayed as INTEGER 0–10 with no conversion layer.
Previous 0–100 proposal rejected as unnecessarily complex (see ADR-001).
Thresholds: `threshold_low = 5` (auto-queue/apply), `threshold_high = 7` (approval required, 7 included).
Emoji mapping: 🟢 ≥7 · 🟡 5–6 · 🔴 <5.

### LLM-assisted scoring (not heuristic-only)
PR-3 adds Claude Haiku as the primary scorer.
Retry once with Claude Sonnet on any failure.
Decision justified by: structured output reliability, Russian-language explanation quality.
Heuristic pre-filter (negative_signals, excluded_industries) remains on the prompt level.

### Worker pattern (not inline scoring)
Scoring runs in a background asyncio.Task, not inline in the Telegram handler.
Telegram handler returns "Сохранено" immediately; scoring notification arrives as a second message.
Rationale: LLM calls take 1–5 s; blocking the handler degrades UX and risks timeout.

### LLM output validation: strict Pydantic schema
Every LLM response is parsed and validated before persisting.
`ScoringOutput`: score int 0–10, reasons list (min 1 item), explanation str (10–500 chars, Russian).
Invalid output → retry with fallback model → skip + log if still fails.

### PII redaction: salary_signal only
Exact salary figure (`salary_min`) is never sent to the LLM.
Replaced with `salary_signal = "has_minimum_threshold" | "no_minimum_specified"`.
All other profile fields use an explicit allowlist in `prepare_profile_for_llm()`.

### Auth: Telegram whitelist enforced at handler level
`is_authorized()` called as the first statement in every Telegram handler.
Empty `ALLOWED_TELEGRAM_IDS` = dev mode (all users allowed, WARNING logged).
Production deployments must set `ALLOWED_TELEGRAM_IDS` in `.env`.

## PR-4 Decisions (Policy Engine)
- Action types (Founder contract):
  - IGNORE: score < 5 — silent, no notification
  - AUTO_QUEUE: score 5-6, non-hh source, within daily limit
  - AUTO_APPLY: score 5-6, source='hh', within daily limit
  - HOLD: score 5-6, daily limit reached — one summary notification/day, not per-vacancy
  - APPROVAL_REQUIRED: score >= 7 (7 included, not only 8+) — never blocked by daily limit
- Daily limit counts AUTO_QUEUE + AUTO_APPLY both (not only AUTO_APPLY).
- Policy engine is inline in scoring worker (not a separate asyncio task): deterministic, <1ms.
- HOLD summary: emit(policy.hold_summary) BEFORE send_message for durability (dedup marker survives Telegram failures).
- HOLD summary tracking: via policy.hold_summary event in events table, sent once per UTC day.
- Migration 004: ALTER TABLE only (non-destructive), adds score/reason/actor/correlation_id to actions.

## PR-5 Decisions (Telegram Approval UX)
- Snooze = status marker only; no timer/reminder in MVP (simplest safe option)
- Callback format: `{action}:{action_id}` where action ∈ {approve, reject, snooze}
- control_plane code in its own skill (control_plane), not embedded in scoring worker
- All status transitions from 'pending' only; idempotent (WHERE status='pending' + rowcount check)
- updated_at tracks operator action timestamp (migration 005, non-destructive)
- is_callback_authorized() is separate from is_authorized(): CallbackQuery.from_user is always present, Message.from_user may not be for some message types
- Double-click protection: second attempt returns "Уже обработано", no crash, no duplicate event
- emit(vacancy.*) happens BEFORE callback.answer() to ensure audit durability
- Keyboard is removed (edit_reply_markup with empty markup) after any decision
