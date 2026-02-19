# Decisions (katerina-ai-twin)

## Product scope v0.1
- Capability: career_os (Career Operating System)
- Control Plane: Telegram (fast ops + approvals)
- Analytics Plane: Web UI later (weekly/daily analytics)

## Scoring & policy
- score scale: 0..10
- score < 5: discard (do not apply)
- score 5..7: auto-send candidate (subject to daily limit)
- score > 7: generate cover package -> approval required

## Limits
- auto_send_limit_per_day: 40 (configurable)

## Sources (v0.1)
- Telegram channels: @geekjobs, @forproducts, @g_jobbot, @careerstation_pm, @careerspace
- Ingestion method: user forwards posts to the bot (first), later direct channel integration

## Language
- User-facing text: Russian
- Code/internal identifiers: English
