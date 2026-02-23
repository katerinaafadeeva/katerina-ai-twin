# QA / SECURITY GATE — PR-5

## Role
You are the QA reviewer. Audit critically. Report issues only.
All output must be in Russian.

## Files to review

- `core/migrations/005_actions_updated_at.sql`
- `capabilities/career_os/skills/control_plane/handlers.py`
- `capabilities/career_os/skills/control_plane/store.py`
- `capabilities/career_os/skills/control_plane/SKILL.md`
- `capabilities/career_os/skills/match_scoring/worker.py` (CHANGES ONLY — inline keyboard)
- `connectors/telegram_bot.py` (CHANGES ONLY — handler registration)
- `tests/test_control_plane_store.py`
- `tests/test_control_plane_handlers.py`

## Checklist

### Business logic (CRITICAL — per Founder contract)
- [ ] ONLY actions with action_type='APPROVAL_REQUIRED' AND status='pending' can be approved/rejected/snoozed
- [ ] Approve: status='approved', updated_at set, event vacancy.approved emitted
- [ ] Reject: status='rejected', updated_at set, event vacancy.rejected emitted
- [ ] Snooze: status='snoozed', updated_at set, event vacancy.snoozed emitted
- [ ] Double-click protection: second attempt returns "Уже обработано", no crash
- [ ] Policy rules UNCHANGED (evaluate_policy and engine.py NOT modified)
- [ ] /today shows correct counts per action_type and status
- [ ] /limits shows policy thresholds + remaining capacity
- [ ] /stats shows pending APPROVAL_REQUIRED list

### Security
- [ ] Callback handler checks authorization (from_user.id in ALLOWED_TELEGRAM_IDS)
- [ ] All command handlers check is_authorized(message)
- [ ] callback_data parsing does not crash on malformed input
- [ ] SQL is parameterized (no f-strings, no .format())
- [ ] No secrets in code or logs

### Data integrity
- [ ] Migration 005: only ADD COLUMN (non-destructive)
- [ ] update_action_status uses WHERE status='pending' (prevents invalid transitions)
- [ ] update_action_status checks rowcount (idempotent)
- [ ] Events emitted with correct event_name, actor, correlation_id
- [ ] action_id in callback_data matches actions.id (not job_raw_id)

### Integration
- [ ] APPROVAL_REQUIRED notification in worker.py now includes InlineKeyboardMarkup
- [ ] save_action return value (action_rowid) is captured and used in callback_data
- [ ] Callback handler registered in telegram_bot.py
- [ ] Command handlers registered in telegram_bot.py
- [ ] answer_callback_query always called (prevents button spinning)
- [ ] Original message edited after callback (keyboard removed)

### Tests
- [ ] State transitions: pending→approved, pending→rejected, pending→snoozed
- [ ] Invalid transitions: approved→approved, rejected→approved, etc. return False
- [ ] updated_at set on transition, NULL before
- [ ] get_today_summary returns correct counts
- [ ] get_pending_approvals filters correctly
- [ ] Callback data parsing tests
- [ ] All 95 existing + new tests pass: `python3 -m pytest -q`

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
