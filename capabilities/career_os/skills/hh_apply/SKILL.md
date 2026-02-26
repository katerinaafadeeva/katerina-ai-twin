# Skill: hh_apply

## Purpose
Browser-based automatic job application on HH.ru for vacancies that passed scoring and policy.
Operates on `AUTO_APPLY` actions created by the policy engine.

## Trigger
- `action_type = 'AUTO_APPLY'` AND `status = 'pending'`
- Vacancy has a `hh_vacancy_id` (from HH ingest)
- `HH_APPLY_ENABLED=true` in config

## Inputs
- `actions` table — task queue (AUTO_APPLY, status=pending)
- `job_raw` table — source of `hh_vacancy_id`
- `cover_letters` table — pre-generated cover letter for the action
- Playwright browser context authenticated via `identity/hh_storage_state.json`

## Outputs
- Updates `actions.execution_status` (done / already_applied / manual_required / captcha / session_expired / failed)
- Updates `actions.execution_attempts`, `actions.applied_at`, `actions.hh_apply_url`
- Emits events: `apply.done`, `apply.failed`, `apply.manual_required`, `apply.captcha`, `apply.session_expired`
- Sends Telegram notifications for all outcomes except `failed` (silent retry)

## Execution rules
- Zero LLM calls — pure browser automation
- Feature flag `HH_APPLY_ENABLED=false` by default (safe opt-in)
- Daily cap: `APPLY_DAILY_CAP=10` (checked before each batch)
- Anti-ban: random delay `[APPLY_DELAY_MIN, APPLY_DELAY_MAX]` seconds between applies
- Batch size: `APPLY_BATCH_SIZE=5` applies per worker cycle
- Captcha → immediate stop of entire batch (human action required)
- Max 3 attempts per task (then marked `failed` permanently)
- All browser operations in try/except — apply failure does NOT crash the bot

## Files
- `store.py` — SQL queries (get tasks, update status, cap count)
- `worker.py` — async background loop
- `notifier.py` — Telegram notification helpers
- `SKILL.md` — this file

## Anti-ban guarantees
- Random delays between applies (not fixed interval)
- Realistic User-Agent and viewport in browser context
- Batch size cap per cycle
- Daily cap across all cycles
- Captcha detection stops the batch immediately

## Security
- `identity/hh_storage_state.json` is gitignored (contains session cookies)
- No cookies, auth tokens, or credentials are logged
- Bootstrap is a separate manual script (`connectors/hh_browser/bootstrap.py`)
