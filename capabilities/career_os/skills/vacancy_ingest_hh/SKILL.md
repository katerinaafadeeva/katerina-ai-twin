---
name: vacancy_ingest_hh
description: Pulls vacancies from HH.ru API and feeds them into the scoring pipeline
---

# Vacancy Ingest — HH.ru (v0.1)

## When activated
Background worker polls HH API on configurable interval (default 1h, `HH_ENABLED=true`).
Uses search queries defined in `identity/hh_searches.json` (gitignored).

## Flow
1. Load search queries from `hh_searches.json`
2. For each query: fetch paginated results from HH.ru API (anonymous, no OAuth)
3. Pre-filter: reject vacancies with negative signals/excluded industries (no LLM cost)
4. Dedup: by `hh_vacancy_id` (HH-specific) + `canonical_key` (cross-source TG↔HH)
5. Save new vacancies to `job_raw` with `source="hh"`
6. Emit `vacancy.ingested` event → picked up by existing scoring worker

## Output
- `job_raw` records: `source="hh"`, `source_message_id="hh_{vacancy_id}"`
- Events: `vacancy.ingested` (per new vacancy), `hh.search_completed` (per cycle)

## Dedup levels
1. `hh_vacancy_id` column — fastest, HH-native lookup
2. `canonical_key` — SHA256 of normalized text, catches TG↔HH duplicates
3. DB UNIQUE index on `(source, source_message_id)` — safety net

## Security
- Anonymous API access only (no OAuth, no HH tokens stored)
- Search queries in gitignored `identity/hh_searches.json`
- Vacancy text NOT logged (stored in DB only)
- `HH_USER_AGENT` configurable via `.env`

## No LLM
Ingestion is purely deterministic. Scoring handled by existing `match_scoring` worker.

## Apply flow
Apply via Playwright automation (PR-8). HH applicant API is closed to third parties.
