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
- score < 5: ignore
- 5 <= score <= 7: auto-send candidate (within daily cap)
- score > 7: generate application package (CV variant + cover) -> approval required
Guardrails:
- daily auto-send limit: default 40 (configurable)
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
- No LLM for deterministic parts: ingestion, dedup, scoring heuristics, policy, counters.
- LLM allowed only for high-value outputs:
  - cover letters for score > 7
  - aggregated weekly market analysis (sampled data)
- Caching and minimal context injection mandatory.
