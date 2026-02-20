# QA / SECURITY GATE — PR-4

## Role
You are the QA reviewer. Audit critically. Report issues only.

## Files to review
- `core/migrations/004_actions_extend.sql`
- `capabilities/career_os/skills/apply_policy/engine.py`
- `capabilities/career_os/skills/apply_policy/store.py`
- `capabilities/career_os/skills/apply_policy/SKILL.md`
- `capabilities/career_os/skills/match_scoring/worker.py` (CHANGES ONLY)
- `tests/test_policy_engine.py`
- `tests/test_policy_store.py`

## Checklist

### Business logic (CRITICAL — per Founder contract)
- [ ] score < 5 → IGNORE (silent, no Telegram notification)
- [ ] score 5-6, source=hh, limit OK → AUTO_APPLY
- [ ] score 5-6, other source, limit OK → AUTO_QUEUE
- [ ] score 5-6, limit reached → HOLD
- [ ] score >= 7 → APPROVAL_REQUIRED (7 included, not only 8+)
- [ ] HOLD: NO per-vacancy notification
- [ ] HOLD: ONE summary notification per day via policy.hold_summary event
- [ ] APPROVAL_REQUIRED: NOT affected by daily limit
- [ ] evaluate_policy() is pure function (no DB, no side effects)

### Data integrity
- [ ] save_action uses parameterized SQL
- [ ] get_today_auto_count counts AUTO_QUEUE + AUTO_APPLY (both, not only AUTO_APPLY)
- [ ] get_today_hold_count counts ONLY HOLD
- [ ] was_hold_notification_sent_today checks events table correctly
- [ ] Migration 004 only ADDs columns
- [ ] actions.action_type values match ActionType enum

### Integration
- [ ] Policy runs AFTER save_score in worker
- [ ] vacancy.policy_applied event emitted with action_type
- [ ] Old notification block REMOVED (replaced with new)
- [ ] correlation_id flows through

### Tests
- [ ] All 5 action types have dedicated tests (IGNORE, AUTO_QUEUE, AUTO_APPLY, HOLD, APPROVAL_REQUIRED)
- [ ] Boundaries: score=4 (IGNORE), score=5 (AUTO), score=6 (AUTO), score=7 (APPROVAL_REQUIRED), limit exact
- [ ] Counter tests: AUTO_QUEUE+AUTO_APPLY both counted, HOLD not counted as auto, IGNORE not counted
- [ ] HOLD notification tracking tested
- [ ] `pytest -v` — ALL tests pass (old 41 + new)

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
