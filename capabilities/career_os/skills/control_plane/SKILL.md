---
name: control_plane
description: Operator control — approval flow, commands, policy monitoring
---

# Control Plane (v1 — Telegram Approval UX)

## Responsibilities

### Approval Flow
- Receive inline button callbacks (approve/reject/snooze)
- Validate: only APPROVAL_REQUIRED + pending can transition
- Update action status + emit event
- Edit original message to reflect decision

### Operator Commands
- /today — daily summary (ingested, scored, actions by type/status, limit usage)
- /limits — policy thresholds and remaining capacity
- /stats — detailed summary + list of pending approvals

## Authorization
All callbacks and commands check ALLOWED_TELEGRAM_IDS.

## No LLM
All queries are deterministic SQL. No LLM calls.
