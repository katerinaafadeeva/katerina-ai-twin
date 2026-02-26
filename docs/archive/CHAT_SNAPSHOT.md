# Chat Snapshot — Katerina AI Twin (Context Freeze)

## Big idea (do not lose)
We are building a full personal AI Twin OS, not just a vacancy bot.
Telegram is the fast operator interface (control plane).
Web UI is the analytics workspace (daily/weekly decision-making).
Data sources include HH.ru (primary funnel) and Telegram channels (secondary), later others.

## What is already implemented
- Repo scaffold: capabilities/career_os/skills + core/connectors/memory/tests
- Claude Code integration via skills symlink
- PR-1 done & pushed: SQLite foundation (job_raw/events/actions/policy) + init_db()
- PR-2 done & pushed: Telegram bot ingest + dedup + emits vacancy.ingested
- Local manual test confirmed: forwarding posts saves to SQLite and dedup works

## Current product rules
Score 0..10:
- <5 ignore
- 5..7 auto-flow (daily limit default 40)
- >7 approval + cover package
Anti-duplicates required.

## Sources roadmap
- v0.1: Telegram forward + HH ingestion minimal (from user-provided saved search URLs)
- v0.2+: better HH automation + optional direct TG channel ingestion
- v1.0: unified multi-source pipeline + web analytics

## Where we are right now (next step)
Start PR-3: match_scoring (heuristic, no LLM) + tests + memory/profile.json.
Then PR-4 apply_policy, PR-5 Telegram approvals, PR-6 HH ingest v0.1.
