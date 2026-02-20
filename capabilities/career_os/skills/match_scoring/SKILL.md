---
name: match_scoring
description: LLM-assisted vacancy scoring with structured output
---

# Match Scoring (v1 — LLM-Assisted)

## Input
- job_raw record (raw_text, id)
- Profile (from identity/profile.json)

## Output
- score: 0–10 (INTEGER)
- reasons: [{criterion, matched, note}]
- explanation: 1-2 sentences in Russian

## Flow
1. Worker picks up unscored vacancy (event-driven poll)
2. Sanitize vacancy text (remove injection vectors, truncate)
3. Prepare profile (redact PII — no exact salary)
4. Call LLM (Claude Haiku, temperature=0, structured JSON output)
5. Validate response (Pydantic schema)
6. Persist to job_scores (idempotent: UNIQUE on job_raw_id + scorer_version)
7. Emit vacancy.scored event
8. Notify user via Telegram (second message)

## Idempotency
- Same job_raw_id + same scorer_version → no re-scoring
- Worker checks before calling LLM

## Error handling
- LLM failure → log + skip + retry on next cycle
- Validation failure → retry once with fallback model → skip + log
