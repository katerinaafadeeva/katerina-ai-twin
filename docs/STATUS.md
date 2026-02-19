# Status

## Date: 2026-02-19

### Done
- PR-1: SQLite foundation (job_raw/events/actions/policy) + init_db
- PR-2: Telegram ingest + dedup + event emission; tested end-to-end

### Next (execution order)
- PR-3: match_scoring (0..10 heuristic + reasons + tests + profile)
- PR-4: apply_policy (limits + anti-duplicates + actions log)
- PR-5: Telegram approval flow + operator commands
- PR-6: HH ingest v0.1 (saved search URLs -> job_raw -> digest)

### Notes
- Telegram is control plane; HH is primary funnel source in roadmap.
- Web analytics is planned in Milestone M2 after pipeline stabilizes.
