# PR-5 Review Checklist (Chief Architect)

## Approval flow
- [ ] InlineKeyboardMarkup attached to APPROVAL_REQUIRED notifications
- [ ] Callback format: `{action}:{action_id}` with action ∈ {approve, reject, snooze}
- [ ] Authorization checked on every callback
- [ ] Only pending + APPROVAL_REQUIRED actions can transition
- [ ] Transitions: pending → approved / rejected / snoozed
- [ ] updated_at populated on transition
- [ ] Events emitted: vacancy.approved / vacancy.rejected / vacancy.snoozed
- [ ] Original message edited after action (keyboard removed, status appended)
- [ ] answer_callback_query called in all paths (no spinning buttons)

## Commands
- [ ] /today — daily summary with action counts + limit usage
- [ ] /limits — policy thresholds + remaining capacity
- [ ] /stats — summary + pending approvals list
- [ ] All commands check is_authorized()
- [ ] All queries are deterministic (no LLM)

## Architecture
- [ ] Control plane logic in control_plane skill (not in scoring worker)
- [ ] Worker.py changes minimal (only inline keyboard addition)
- [ ] Migration 005: ALTER TABLE only (non-destructive)
- [ ] No policy engine modifications

## Tests
- [ ] State transition tests (all valid + invalid)
- [ ] Command query tests
- [ ] Callback parsing tests
- [ ] All 95+ existing tests still pass

## Documentation
- [ ] STATUS.md → PR-5 done
- [ ] CHANGELOG.md → PR-5 entry
- [ ] DECISIONS.md → PR-5 decisions (snooze semantics, callback format)
- [ ] BACKLOG.md → PR-5 marked DONE
- [ ] control_plane SKILL.md updated

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
