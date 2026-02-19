---
name: control_plane
description: Operational control layer for Katerina AI Twin
---

# Control Plane

This skill manages operational commands and policies for the AI Twin.

## Responsibilities

- manage scoring thresholds
- manage daily auto-send limits
- expose operational commands
- store policy updates

## Commands (future Telegram mapping)

- /policy
- /limits
- set threshold <value>
- set daily_limit <value>

## Outputs

- confirmation messages
- updated policy state
