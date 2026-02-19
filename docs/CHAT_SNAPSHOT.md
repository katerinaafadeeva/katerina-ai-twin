# Chat Snapshot — Katerina AI Twin (as of 2026-02-19)

## Goal
Build personal AI Twin (Life OS). Start with Career OS v0.1.

## Interaction model
- Telegram = speed: commands, approvals, notifications
- Web UI = beauty + analytics: daily/weekly reviews, funnel, market trends, CV+learning gaps

## v0.1 core loop
Forward TG vacancy -> ingest -> store raw -> score 0..10 -> policy -> notify/approve.

## Scoring & policy
- Score scale: 0..10
- <5: do nothing
- 5–7: auto-send candidate (limit 40/day, configurable)
- >7: generate cover package -> user approval
- anti-duplicates required

## Architecture decisions
- Capability-driven + Skills
- Modular monolith core
- SQLite first
- Events + Actions log
- Hybrid execution: scheduled + manual
- User-facing RU, internal EN

## Dev process (AI team)
- 1 change = 1 PR
- No overengineering
- Tests/fixtures early
- DECISIONS.md is source of truth
