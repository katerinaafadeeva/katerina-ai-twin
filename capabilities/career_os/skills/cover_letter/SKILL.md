---
name: cover_letter
description: LLM-generated cover letters for HH auto-apply and approval flows
---

# Cover Letter Generation (v1 — MVP)

## When activated
After policy evaluation routes a vacancy to AUTO_APPLY or APPROVAL_REQUIRED.

## Input
- job_raw record (raw_text)
- Profile (from identity/profile.json)
- Score reasons from job_scores (List[ScoreReason])
- Action type (AUTO_APPLY or APPROVAL_REQUIRED)

## Output
- Cover letter text (2-4 paragraphs, Russian, professional)
- Stored in cover_letters table with is_fallback flag, tokens, cost

## Flow
1. Check daily cap (cover_letter_daily_cap)
2. If cap reached → use fallback template
3. Prepare context: vacancy text (sanitized) + profile (PII-redacted) + score reasons
4. Call LLM (Claude Haiku, temperature=0.3)
5. Basic validation (length ≥ 50 chars)
6. If LLM fails or response too short → use fallback template
7. Store in cover_letters table (INSERT OR IGNORE — idempotent)
8. Return letter text for Telegram notification (APPROVAL_REQUIRED preview)
   or Playwright apply (AUTO_APPLY, PR-8)

## Fallback
When LLM is unavailable, cap reached, or response too short:
- Load identity/cover_letter_fallback.txt (user-customisable, gitignored)
- Falls back to .example.txt if real file absent
- Falls back to hardcoded minimal text if neither file exists
- Stored with is_fallback=1 in cover_letters table
- No LLM cost

## Security
- Vacancy text sanitized via sanitize_for_llm() before LLM call
- Profile PII-redacted via prepare_profile_for_llm() (exact salary → salary_signal)
- Cover letter text stored in DB only — not written to events payload or logs
- Audit: llm.call event emitted for every LLM cover letter call
- Prompt injection defence: <vacancy>/<profile>/<reasons> tags + NEVER-follow instruction

## No policy logic
This skill generates text only. Policy decisions are made by apply_policy/engine.py.
Routing (which vacancies get cover letters) is controlled by scoring worker.

## PR-8 integration points
- cover_letters.letter_text read by Playwright apply module
- cover_letters.action_id links to actions row for approval flow
- is_fallback=1 rows may be regenerated via LLM before apply (future enhancement)
