# PR-4 Review Checklist (Chief Architect)

### Policy logic
- [ ] evaluate_policy is pure function (no DB, no side effects)
- [ ] ActionType enum: IGNORE, AUTO_QUEUE, AUTO_APPLY, HOLD, APPROVAL_REQUIRED
- [ ] Boundaries (Founder contract): <5 IGNORE, 5-6 AUTO_QUEUE/AUTO_APPLY, >=7 APPROVAL_REQUIRED (7 included)
- [ ] Daily limit counter: COUNT(AUTO_QUEUE + AUTO_APPLY) for today UTC
- [ ] APPROVAL_REQUIRED not affected by daily limit

### Integration
- [ ] Policy runs inline in scoring worker (not separate process)
- [ ] Event: vacancy.policy_applied emitted with action_type
- [ ] Actions table: new record per scored vacancy
- [ ] IGNORE → no Telegram notification (silent)
- [ ] HOLD → no per-vacancy notification; one daily summary
- [ ] AUTO_QUEUE / AUTO_APPLY / APPROVAL_REQUIRED → notification with action label

### Data
- [ ] Migration 004: ALTER TABLE only (no destructive changes)
- [ ] Policy table defaults work (5/7/40)
- [ ] Existing 41 tests still pass

### New tests
- [ ] All 4 action types
- [ ] Boundary values (score=5, score=7, limit=N count=N)
- [ ] Counter logic
- [ ] Store persistence

### Documentation
- [ ] STATUS.md → PR-4 done
- [ ] DECISIONS.md → policy engine decisions
- [ ] CHANGELOG.md → PR-4 entry
- [ ] BACKLOG.md → PR-3/4 marked DONE
- [ ] Stale docs cleaned

## Verdict: PASS / PASS WITH CONDITIONS / FAIL
