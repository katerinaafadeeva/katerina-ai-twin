# PR-6 Review Checklist (Chief Architect)

**Reviewer:** Chief Architect (Opus)
**When:** After Tech Lead reports PR-6 complete, before merge to main.

---

## HH API Connector
- [ ] connectors/hh_api.py exists as standalone connector (no business logic)
- [ ] Uses httpx (async HTTP client)
- [ ] Rate limiting enforced (≤1 req/sec)
- [ ] Exponential backoff on 429/5xx (max 3 retries)
- [ ] Timeout: 30s per request
- [ ] User-Agent from config (not hardcoded)
- [ ] Pagination support (page 0..N, per_page=100)
- [ ] Returns typed data (list of vacancy dicts or Pydantic models)
- [ ] No business logic in connector (pure HTTP transport)

## HH Ingest Skill
- [ ] Located at capabilities/career_os/skills/vacancy_ingest_hh/
- [ ] SKILL.md with contract (input/output/flow/no-LLM-note)
- [ ] handler.py: orchestration (load queries → API → prefilter → store → emit)
- [ ] store.py: dedup + persistence (three levels: hh_id, canonical_key, DB unique)
- [ ] prefilter.py: deterministic rejection (negative_signals + industries_excluded)
- [ ] worker.py: async poll loop (configurable interval)

## Dedup Strategy (Three Levels)
- [ ] Level 1: source_message_id = "hh_{id}" (same vacancy from same search)
- [ ] Level 2: canonical_key = SHA256 of normalized title (cross-source TG↔HH)
- [ ] Level 3: DB UNIQUE index on (source, source_message_id) — safety net
- [ ] No duplicate vacancies in job_raw after running same search twice
- [ ] HH vacancy already forwarded via TG: detected and not re-ingested

## Pre-filter (Deterministic, No LLM)
- [ ] Checks negative_signals from Profile
- [ ] Checks industries_excluded from Profile
- [ ] Case-insensitive matching
- [ ] Rejected vacancies do NOT consume LLM budget
- [ ] Profile loaded from config path (same as scoring worker)

## Scoring Daily Cap
- [ ] HH_SCORING_DAILY_CAP in config (default 100)
- [ ] Cap checked in scoring worker BEFORE LLM call
- [ ] Unscored vacancies remain in DB for next day
- [ ] One Telegram notification when cap reached (not per-vacancy)
- [ ] Cap tracks scoring_cap_reached event in events table for dedup

## Storage
- [ ] job_raw.hh_vacancy_id populated (TEXT, indexed)
- [ ] job_raw.source = "hh"
- [ ] job_raw.source_message_id = "hh_{vacancy_id}"
- [ ] job_raw.raw_text = concatenation of name + snippet fields
- [ ] job_raw.canonical_key = SHA256 of normalized title

## Event Audit
- [ ] vacancy.ingested emitted per new HH vacancy (actor="hh_ingest", source="hh")
- [ ] hh.search_completed emitted per poll cycle (payload: query_count, new_count, filtered_count)
- [ ] Events have correlation_id

## Worker Integration
- [ ] HH worker started in telegram_bot.py as asyncio.Task
- [ ] Only starts if HH_ENABLED=true
- [ ] Does not block or interfere with scoring_worker
- [ ] Graceful handling of missing hh_searches.json (log warning, no crash)

## Config & Secrets
- [ ] .env.example has all HH_* variables with safe defaults
- [ ] HH_ENABLED=false by default
- [ ] identity/hh_searches.json in .gitignore
- [ ] identity/hh_searches.example.json committed (template)
- [ ] requirements.txt includes httpx
- [ ] No secrets in code or logs

## Policy Engine Impact
- [ ] engine.py NOT modified (git diff empty)
- [ ] HH vacancies with score 5-6 route to AUTO_APPLY (verified by existing test)
- [ ] All existing 130 tests pass

## New Tests
- [ ] ≥25 new tests
- [ ] Connector: mock HTTP responses, rate limiting, pagination, error handling
- [ ] Ingest: handler orchestration, dedup (same source + cross-source)
- [ ] Prefilter: negative signals, excluded industries, pass-through, case-insensitive
- [ ] Store: persistence, hh_vacancy_id populated
- [ ] Scoring cap: cap enforcement, reset logic
- [ ] Total: 130 + ≥25 = ≥155 tests, all green

## Documentation
- [ ] STATUS.md: PR-6 DONE, PR-7 NEXT
- [ ] CHANGELOG.md: PR-6 section with Added/Changed
- [ ] DECISIONS.md: HH API decisions (anonymous access, official API, pre-filter, scoring cap)
- [ ] BACKLOG.md: PR-6 DONE, updated roadmap
- [ ] SKILL.md: vacancy_ingest_hh contract

## Post PR-6 Roadmap Alignment
- [ ] PR-7 (data normalization) correctly identified as next
- [ ] MVP v1 complete after PR-6
- [ ] No premature features (no OAuth, no auto-apply API, no cover letters)

---

## Verdict: PASS / PASS WITH CONDITIONS / FAIL

**Checklist complete. If all items checked → PASS.**
**If CRITICAL items unchecked → FAIL (must fix before merge).**
**If only LOW/MEDIUM items unchecked → PASS WITH CONDITIONS (fix in follow-up).**
