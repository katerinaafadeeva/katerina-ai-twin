# QA / SECURITY GATE — PR-3 Review

## Role
You are the QA and Security reviewer. Audit the code critically.
Do NOT implement anything. Report issues only.

## What to review

Read ALL files created/modified in PR-3:
- core/config.py
- core/security.py
- core/db.py
- core/events.py
- core/migrations/migrate.py
- core/migrations/*.sql
- core/llm/client.py
- core/llm/sanitize.py
- core/llm/schemas.py
- core/llm/prompts/scoring_v1.py
- capabilities/career_os/models.py
- capabilities/career_os/skills/match_scoring/handler.py
- capabilities/career_os/skills/match_scoring/worker.py
- capabilities/career_os/skills/match_scoring/store.py
- connectors/telegram_bot.py
- tests/ (all test files)
- .env.example
- requirements.txt

## Checklist

### Security
- [ ] All Telegram handlers check `is_authorized()`
- [ ] No secrets in code or logs (grep for API key patterns, token patterns)
- [ ] LLM input sanitized (zero-width chars, control chars, truncation)
- [ ] PII redacted before LLM call (no exact salary in profile sent to LLM)
- [ ] Prompt injection defense: vacancy text in <vacancy> tags, system prompt forbids instruction following
- [ ] LLM output validated via Pydantic schema (score range, required fields)
- [ ] SQL uses parameterized queries only (no f-strings, no .format())
- [ ] .env.example has no secret values
- [ ] .gitignore includes identity/, .env, data/, *.db

### Code Quality
- [ ] All public functions have type hints
- [ ] All public functions have docstrings
- [ ] No `print()` statements (must use `logging`)
- [ ] No global mutable state (except config singleton which is frozen)
- [ ] Imports are clean (no circular, no unused)
- [ ] Error handling: exceptions logged with context, not silently swallowed
- [ ] No hardcoded values that should be in config

### Data Integrity
- [ ] job_scores has UNIQUE constraint on (job_raw_id, scorer_version)
- [ ] save_score uses INSERT OR IGNORE (idempotent)
- [ ] get_unscored_vacancies uses LEFT JOIN correctly
- [ ] Migrations are numbered and applied in order
- [ ] events.emit() uses actor and correlation_id
- [ ]  Score range CHECK constraint: BETWEEN 0 AND 10

### Testing
- [ ] All tests pass: `pytest -v`
- [ ] Schema validation: rejects score < 0 or > 10 (overflow 11+/100 rejected), empty reasons, short explanation
- [ ] Sanitization: removes zero-width, control chars; preserves newlines; truncates
- [ ] PII redaction: no exact salary in LLM-bound profile
- [ ] Store: idempotent save, unscored query, score retrieval
- [ ] Config: loads from env, handles empty whitelist
- [ ] Injection fixture exists and is tested

### Architecture
- [ ] Scoring NOT inline in Telegram handler (worker pattern)
- [ ] Worker is async, does not block event loop
- [ ] LLM client is separate from scoring logic
- [ ] Profile model is separate from DB layer
- [ ] Events emitted for: vacancy.ingested, vacancy.scored, llm.call

## Output format

For each issue found, report:

```
[SEVERITY] FILE:LINE — Description
  Recommendation: ...
```

Severity levels:
- **CRITICAL** — Must fix before merge (security, data loss, crash)
- **HIGH** — Should fix before merge (logic error, missing validation)
- **MEDIUM** — Fix in follow-up (code quality, naming)
- **LOW** — Nice to have (style, optimization)

If no issues found in a section, state: "✅ No issues found."

## Final verdict

After review, state one of:
- **PASS** — Ready to merge
- **PASS WITH CONDITIONS** — Merge after fixing CRITICAL/HIGH issues
- **FAIL** — Requires significant rework
