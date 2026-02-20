---
name: apply_policy
description: Deterministic policy evaluation for scored vacancies — routes score to action type
---

# Apply Policy (v1 — Deterministic)

## Input
- score (int, 0–10)
- source (str): vacancy origin — 'hh' or 'tg' / 'telegram_forward'
- policy record (threshold_low, threshold_high, daily_limit from policy table)
- today_auto_count (int): AUTO_QUEUE + AUTO_APPLY actions already recorded today

## Output
- action_type: IGNORE | AUTO_QUEUE | AUTO_APPLY | HOLD | APPROVAL_REQUIRED
- reason: human-readable string (Russian)

## Business Rules (Founder contract — source of truth)

1. **score < threshold_low (5)** → `IGNORE`
   - Silent. No Telegram notification.

2. **score >= threshold_high (7)** → `APPROVAL_REQUIRED`
   - score 7, 8, 9, 10 all route here.
   - Telegram: approval required notification.
   - NOT affected by daily limit.

3. **score in [threshold_low, threshold_high − 1] (5–6):**
   - If today_auto_count >= daily_limit → `HOLD`
     - Silent per vacancy. ONE summary notification per day.
   - Else, source-aware:
     - source == 'hh' → `AUTO_APPLY` (HH auto-apply; execution in PR-6)
     - source == anything else (tg, telegram_forward…) → `AUTO_QUEUE`

## Daily Limit

- Counts both AUTO_QUEUE and AUTO_APPLY toward the daily cap.
- Default daily_limit = 40.
- HOLD summary emitted via `policy.hold_summary` event (max once per UTC day).

## No LLM

Purely deterministic. Cover letter generation is a separate skill (PR-5).
