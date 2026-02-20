# Career AI Twin — PR-4 Implementation Prompt (SOURCE-OF-TRUTH)

You are the Implementation Agent. Work only inside branch `pr-4`.
Do NOT re-architect PR-3. Add deterministic policy engine.

## Non-negotiable Business Contract (Founder)
Score scale is 0–10.

If score < 5:
  - action: IGNORE
  - no Telegram notification

If score in [5,6]:
  - if daily limit reached: action HOLD; no per-vacancy notify; send ONE daily "limit reached" summary
  - else:
      - source == 'tg'  -> action AUTO_QUEUE (no auto-apply)
      - source == 'hh'  -> action AUTO_APPLY (if API supported later; still record action now)

If score >= 7:
  - action APPROVAL_REQUIRED
  - generate cover letter draft later (PR-5)
  - send Telegram approval notification (simple text for now)

Daily limit applies to AUTO_QUEUE + AUTO_APPLY (both count).

## Required actions enum
IGNORE | AUTO_QUEUE | AUTO_APPLY | APPROVAL_REQUIRED | HOLD

## Constraints
- Deterministic only. NO LLM calls in PR-4.
- Modular monolith, SQLite.
- Worker pattern: integrate inline after save_score in match_scoring worker.
- Event audit required: emit vacancy.policy_applied and policy.hold_summary.

## Files to create/modify
- core/migrations/004_actions_extend.sql
- capabilities/career_os/skills/apply_policy/{__init__.py, SKILL.md, engine.py, store.py}
- capabilities/career_os/skills/match_scoring/worker.py (changes only)
- tests/test_policy_engine.py
- tests/test_policy_store.py
- docs updates: DECISIONS.md / STATUS.md / CHANGELOG.md / BACKLOG.md (sync)

Implement and keep all existing tests green.