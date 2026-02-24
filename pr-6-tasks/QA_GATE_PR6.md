# QA / SECURITY GATE — PR-6

## Role
You are the QA reviewer. Audit critically. Report issues only.
All output must be in Russian.

## When to run
- **After Step 4** (HH ingest skill complete): run sections Business Logic + Data Integrity + Security
- **After Step 9** (all done): full checklist

## Files to review

- `core/migrations/006_job_raw_hh_id.sql`
- `core/config.py` (HH_* fields)
- `connectors/hh_api.py`
- `capabilities/career_os/skills/vacancy_ingest_hh/handler.py`
- `capabilities/career_os/skills/vacancy_ingest_hh/store.py`
- `capabilities/career_os/skills/vacancy_ingest_hh/prefilter.py`
- `capabilities/career_os/skills/vacancy_ingest_hh/worker.py`
- `capabilities/career_os/skills/vacancy_ingest_hh/SKILL.md`
- `capabilities/career_os/skills/match_scoring/worker.py` (CHANGES ONLY — daily cap)
- `connectors/telegram_bot.py` (CHANGES ONLY — HH worker startup)
- `tests/test_hh_api.py`
- `tests/test_hh_ingest.py`
- `tests/test_hh_prefilter.py`
- `identity/hh_searches.example.json`
- `.env.example` (HH_* vars)
- `.gitignore` (hh_searches.json)
- `requirements.txt` (httpx)

## Checklist

### Business logic (CRITICAL — per Founder contract)
- [ ] HH vacancies saved to job_raw with source="hh"
- [ ] source_message_id format: "hh_{vacancy_id}"
- [ ] hh_vacancy_id column populated with raw HH vacancy ID
- [ ] canonical_key generated for cross-source dedup (SHA256 of normalized title)
- [ ] Dedup: same HH vacancy not ingested twice (by source_message_id)
- [ ] Dedup: HH vacancy already forwarded via TG detected by canonical_key check
- [ ] Pre-filter: negative_signals and industries_excluded checked BEFORE LLM (no cost)
- [ ] Pre-filter: rejected vacancies NOT saved to job_raw (or saved with a skip marker)
- [ ] HH vacancies flow through existing scoring → policy → actions pipeline
- [ ] Policy correctly routes HH score 5-6 to AUTO_APPLY (not AUTO_QUEUE)
- [ ] Policy engine code (engine.py) NOT modified
- [ ] vacancy.ingested event emitted with source="hh" for each new HH vacancy
- [ ] hh.search_completed event emitted after each poll cycle
- [ ] HH_ENABLED=false by default (opt-in activation)

### Scoring daily cap (CRITICAL — token economy)
- [ ] HH_SCORING_DAILY_CAP configurable (default 100)
- [ ] Scoring worker checks cap BEFORE LLM call
- [ ] When cap reached: vacancy stays in job_raw, scoring skipped with log
- [ ] When cap reached: Telegram notification sent (once per day, not per vacancy)
- [ ] Next day: cap resets, unscored vacancies processed
- [ ] Cap counter counts ALL sources (not just HH)

### Data integrity
- [ ] Migration 006: only ADD COLUMN + CREATE INDEX (non-destructive)
- [ ] All SQL is parameterized (no f-strings, no .format())
- [ ] job_raw UNIQUE index on (source, source_message_id) prevents HH duplicates
- [ ] hh_vacancy_id index created for fast lookups
- [ ] Search queries loaded from identity/hh_searches.json (gitignored)
- [ ] Example file identity/hh_searches.example.json committed (no personal data)

### Security
- [ ] No HH tokens/secrets in code (anonymous API, but User-Agent in .env)
- [ ] HH_USER_AGENT configurable via .env, not hardcoded
- [ ] Vacancy text NOT logged (saved in DB only)
- [ ] Search query text NOT in event payloads
- [ ] identity/hh_searches.json in .gitignore
- [ ] No secrets in test files
- [ ] TG user IDs protected (existing ALLOWED_TELEGRAM_IDS pattern maintained)

### HH API connector
- [ ] Rate limiting: ≤1 request/second enforced (asyncio.sleep or token bucket)
- [ ] Retry with exponential backoff on HTTP 429 (Too Many Requests)
- [ ] Retry with backoff on HTTP 5xx
- [ ] Max 3 retries per request
- [ ] 30-second timeout per request
- [ ] Valid User-Agent header sent with every request
- [ ] Pagination: fetches up to HH_MAX_PAGES pages (default 5, max 100 per page)
- [ ] Response parsed via Pydantic or dict validation (graceful skip on malformed data)
- [ ] Network errors caught and logged (worker continues on next cycle)

### HH ingest worker
- [ ] Worker runs as asyncio.Task (same pattern as scoring_worker)
- [ ] Polls on configurable interval (HH_POLL_INTERVAL, default 3600)
- [ ] Worker only starts if HH_ENABLED=true
- [ ] Worker loads search queries from HH_SEARCHES_PATH
- [ ] Worker handles empty/missing search queries file gracefully
- [ ] Worker handles HH API downtime gracefully (log + sleep + retry next cycle)

### Integration
- [ ] telegram_bot.py starts hh_ingest_worker as asyncio.Task (conditional on HH_ENABLED)
- [ ] HH worker does NOT interfere with scoring_worker or Telegram handlers
- [ ] Existing 130 tests still pass
- [ ] New tests: ≥25 total (connector mock, ingest dedup, pre-filter, store, worker)

### Tests
- [ ] test_hh_api.py: mocked HTTP responses (success, 429, 5xx, timeout, malformed JSON)
- [ ] test_hh_api.py: rate limiting behavior
- [ ] test_hh_api.py: pagination
- [ ] test_hh_ingest.py: handler orchestration, dedup (same source + cross-source)
- [ ] test_hh_ingest.py: store persistence (hh_vacancy_id populated)
- [ ] test_hh_prefilter.py: negative_signals rejection
- [ ] test_hh_prefilter.py: industries_excluded rejection
- [ ] test_hh_prefilter.py: clean vacancy passes
- [ ] test_hh_prefilter.py: case-insensitive matching
- [ ] Scoring daily cap tests (cap reached → skip, cap reset next day)
- [ ] `python3 -m pytest -q` — ALL tests pass (130 existing + ≥25 new)

### Documentation
- [ ] STATUS.md → PR-6 DONE
- [ ] CHANGELOG.md → PR-6 entry (complete)
- [ ] DECISIONS.md → HH API decisions added
- [ ] BACKLOG.md → PR-6 DONE, PR-7 NEXT
- [ ] SKILL.md created for vacancy_ingest_hh
- [ ] .env.example updated with HH_* variables

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
