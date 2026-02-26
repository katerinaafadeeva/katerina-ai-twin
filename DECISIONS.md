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
- Keyboard is removed (`reply_markup=None`) after any decision — not `InlineKeyboardMarkup(inline_keyboard=[])` which causes aiogram warnings
- callback.answer() called AFTER edit_text + edit_reply_markup (spinner stops last, ensuring message is already updated)

## PR-6 Decisions (HH Ingest v0.1) (2026-02-24)

### Anonymous HH API (no OAuth)
Rationale: OAuth adds credential storage complexity, token refresh, and account risk.
Anonymous API is sufficient for vacancy search (read-only, public data).
Rate limit ≤1 req/sec enforced in `HHApiClient._rate_limit()` via `time.monotonic()`.

### Pre-filter BEFORE LLM (no tokens wasted on filtered vacancies)
`should_score()` checks `negative_signals` + `industries_excluded` against raw_text.
Filtered vacancies are NOT saved to `job_raw` — prevents the scoring worker from picking them up.
Trade-off: no analytics on filtered vacancies. Mitigated by `hh.search_completed` event which includes `filtered` count.

### Three-level dedup
1. `hh_vacancy_id` — fast, HH-native, prevents refetching same page
2. `canonical_key` (SHA256 of first 200 chars lowercased) — cross-source: catches same vacancy forwarded via Telegram then found on HH
3. DB UNIQUE `(source, source_message_id)` — last-resort at DB level (INSERT OR IGNORE)
Same `compute_canonical_key` algorithm as vacancy_ingest_telegram for cross-source compatibility.

### Scoring daily cap (emit-first durability)
`scoring.cap_reached` event emitted BEFORE `bot.send_message()` — same durability pattern as HOLD summary.
If Telegram fails after emit, dedup marker is still persisted → next cycle skips notification.
If emit fails before send_message → no marker → notification sent again next cycle (acceptable: duplicate cap warning is better than silent miss).

### HH_ENABLED=false default (safe opt-in)
Worker exits immediately if `HH_ENABLED` is falsy — no surprise API calls on first deploy.
Operator must explicitly set `HH_ENABLED=true` in `.env`.

### hh_searches.json gitignored (identity data)
Search queries reveal job-search intent (role, location, salary signals) — treated as PII-adjacent.
`identity/hh_searches.example.json` committed as template; real file gitignored.

## PR-7 Decisions (Cover Letter Generation) (2026-02-24)

### Claude Haiku 4.5 for cover letters (not Sonnet)
Haiku is 10× cheaper and sufficient for a 150–400 word structured Russian letter.
Cost per letter ≈ $0.001 at typical token counts (200 in / 300 out).
Sonnet fallback NOT added for cover letters — Haiku failure triggers static fallback template instead.
Rationale: cover letter quality is verified by operator before sending; a static template is acceptable.

### Fallback chain (three levels, never blocks)
1. `identity/cover_letter_fallback.txt` — operator-customised real file (gitignored)
2. `identity/cover_letter_fallback.example.txt` — generic committed template (no PII)
3. Hardcoded default string — last resort, always available
Module-level `_fallback_cache` avoids repeated file I/O.
Static fallback is returned with `is_fallback=True` and tokens=0/cost=0.0 for accurate cap tracking.

### Cover letter daily cap excludes fallbacks
`get_today_cover_letter_count()` counts only `is_fallback=0` rows.
Fallbacks are free (no LLM call) and must not consume quota.
Cap notification uses same emit-first durability pattern as scoring cap and HOLD summary.

### Cover letter in try/except — non-fatal
Cover letter failure must not block vacancy scoring, policy, or Telegram notification.
Outer per-vacancy try/except already protects scoring; cover letter has its own inner try/except.
If generation fails, notification is sent without cover letter preview (cover_letter_text stays None).

### UNIQUE(job_raw_id, action_id) — INSERT OR IGNORE idempotency
Prevents duplicate letters if worker restarts mid-cycle.
`save_cover_letter` returns `cursor.lastrowid` on insert, 0 on duplicate — caller can detect either case.

### cover_letter_fallback.txt gitignored (identity data)
The real fallback template is personal (tone, contact info, self-description).
Committed only the `.example.txt` sibling (generic, no PII).
Same pattern as `identity/profile.json` and `identity/hh_searches.json`.

## PR-8 Decisions (Playwright Auto-Apply) (2026-02-26)

### Lazy Playwright import (never at module level)
`from playwright.async_api import async_playwright` is inside `HHBrowserClient.session()`.
Importing `connectors.hh_browser.client` at startup does NOT require Playwright installed.
If `HH_APPLY_ENABLED=false` (default), Playwright is never imported — no ImportError on clean env.

### apply_runs — execution log separate from actions (decision log)
`actions` is an immutable decision log: `actions.status` tracks operator approval (pending/approved/rejected/snoozed).
`apply_runs` is an execution log: one row per browser attempt, with its own `status` (done/failed/captcha/…), `attempt` number, `apply_url`, `started_at`, `finished_at`.
Separation rationale:
- Multiple retry attempts each get their own row → full audit history, no data loss
- `actions` stays clean and immutable; execution churn doesn't pollute the decision record
- Easier to extend: multiple resumes, screenshots per attempt, multi-channel apply
Idempotency: `UNIQUE(action_id, attempt)` + `INSERT OR IGNORE` prevents duplicate attempt rows.
"No second apply after SUCCESS" rule: enforced by `NOT EXISTS (... status='done')` in `get_pending_apply_tasks` — the worker never picks up a task that already has a successful run.
Queue filter also excludes terminal non-retry statuses: `already_applied`, `manual_required`, `captcha`, `session_expired` — only `failed` (up to MAX_ATTEMPTS=3) is retried.

### Captcha → stop entire batch (not just skip one vacancy)
Captcha on HH.ru typically means the IP/session is under suspicion.
Continuing to apply after captcha detection would worsen the situation.
Stopping the batch and notifying the operator is the safest response.
Human resolves captcha → bot continues on next cycle.

### Session expired → stop entire batch + notify (not auto-re-login)
Auto-re-login requires storing credentials in code or on disk — security risk.
The bootstrap script is a one-time manual operation: operator knows when to re-run it.
Stopping the batch on session expiry is safe; operator re-bootstraps → bot continues.

### Random delay between applies (not fixed)
Fixed delay is easier to detect by anti-bot systems.
`random.uniform(apply_delay_min, apply_delay_max)` mimics human browsing rhythm.
Defaults: 10–30 seconds (aggressive enough to prevent bursts, slow enough not to miss daily cap).

### Apply daily cap enforced BEFORE browser session opens
Opens no browser if cap is already reached.
Emit-first pattern: emit `apply.cap_reached` BEFORE `send_message` (same as scoring/cover-letter caps).
Cap counts only `apply_runs.status = 'done'` + `date(finished_at) = date('now')` — not attempted, not failed.

### MAX_ATTEMPTS = 3 (not infinite retry)
Transient failures (page load timeout, flaky element) are retried up to 3 times.
After 3 attempts the task is marked `failed` permanently — prevents infinite retry loops.
Operator can see failed tasks and decide whether to re-enable manually.

### selectors.py — single file for all DOM selectors
HH.ru changes markup periodically. Keeping all `data-qa` selectors in one file makes updates O(1).
Using `data-qa` attributes is more stable than CSS classes or XPath.

### HH_APPLY_ENABLED=false default (safe opt-in)
Same pattern as HH_ENABLED (PR-6). No surprise browser sessions on first deploy.
Operator must explicitly opt in after running bootstrap.
