# Backlog v0.1 (Career OS)

## Milestone M0 — First working loop (Telegram-first)
Goal: forward a vacancy -> store -> score -> policy decision -> send Telegram card.

### S1: vacancy_ingest_telegram
- Accept forwarded Telegram messages
- Persist raw message + metadata
- Detect "vacancy vs not vacancy" (simple heuristic first)

### S2: match_scoring
- Parse minimal fields (role, company, location/remote, link/contact)
- Compute score 0..10 + reasons list

### S3: apply_policy
- Apply thresholds (<5 discard, 5..7 auto, >7 approval)
- Enforce daily limit + anti-duplicates
- Create action records (send/approve/reject)

### S4: control_plane
- /policy and /limits commands (read-only first)
- Show today stats: ingested, scored, queued, autosent

## Milestone M1 — Approval flow
- Telegram approval cards (Approve/Edit/Reject/Snooze)
- Cover letter generation for score > 7 (cover_letter_writer)

## Milestone M2 — Analytics (web later)
- Daily/weekly summary generation
- Market insights: top skills required, gaps vs CV
