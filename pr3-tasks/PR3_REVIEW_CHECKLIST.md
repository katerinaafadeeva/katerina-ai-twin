# PR-3 Review Checklist (Chief Architect)

## Pre-merge final review

### Architecture compliance
- [ ] Score contract matches ADR-001 (0-100 INTEGER, thresholds 50/70)
- [ ] Worker pattern matches ADR-003 (async in-process, not inline)
- [ ] LLM security matches ADR-004 (sanitization, redaction, validation, audit)
- [ ] Module boundaries respected (llm/ doesn't import career_os/, etc.)
- [ ] No circular dependencies

### Event contract
- [ ] `vacancy.ingested` emitted on new ingest (existing ✓)
- [ ] `vacancy.scored` emitted after scoring (actor=scoring_worker)
- [ ] `llm.call` emitted for every LLM call (tokens, cost, model, prompt_version)
- [ ] All events have correlation_id for tracing

### Score contract
- [ ] Score stored as INTEGER 0-100
- [ ] Display as X.X/10
- [ ] Thresholds: <50 ignore, 50-70 auto, >70 approval
- [ ] Emoji: 🔴 <50, 🟡 50-69, 🟢 ≥70
- [ ] Idempotent: UNIQUE(job_raw_id, scorer_version)

### Telegram UX
- [ ] Forward → immediate "Сохранено: #N ✅"
- [ ] Delayed → "Оценка #N: {emoji} {score}/10\n{explanation}"
- [ ] Duplicate → "Уже в базе: #N" (no re-scoring)
- [ ] Unauthorized → silent ignore

### Files expected
- [ ] core/config.py
- [ ] core/security.py
- [ ] core/migrations/ (migrate.py + 4 .sql files)
- [ ] core/llm/ (client.py, sanitize.py, schemas.py, prompts/scoring_v1.py)
- [ ] capabilities/career_os/models.py
- [ ] capabilities/career_os/skills/match_scoring/ (SKILL.md, handler.py, worker.py, store.py)
- [ ] identity/profile.json
- [ ] tests/ (conftest, test_schemas, test_sanitize, test_store, test_config)
- [ ] tests/fixtures/ (vacancies + profiles)
- [ ] architecture/adr/ (ADR-001 through ADR-005)
- [ ] architecture/governance/ (engineering + security policies)
- [ ] Updated: db.py, events.py, telegram_bot.py, .env.example, requirements.txt, .gitignore

### Documentation
- [ ] STATUS.md updated (PR-3 done, next = PR-4)
- [ ] DECISIONS.md updated (score contract, LLM-assisted scoring)
- [ ] CHANGELOG.md created
- [ ] All new SKILL.md files present

### Tests
- [ ] `pytest -v` all green
- [ ] Coverage of critical paths (scoring, sanitization, persistence, validation)

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
