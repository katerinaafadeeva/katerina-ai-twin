-- Migration 008: execution tracking fields in actions table
-- Tracks browser automation state for AUTO_APPLY actions.
-- Non-destructive ALTER TABLE only.

ALTER TABLE actions ADD COLUMN execution_status TEXT;
ALTER TABLE actions ADD COLUMN execution_error TEXT;
ALTER TABLE actions ADD COLUMN execution_attempts INTEGER DEFAULT 0;
ALTER TABLE actions ADD COLUMN applied_at TEXT;
ALTER TABLE actions ADD COLUMN hh_apply_url TEXT;

CREATE INDEX IF NOT EXISTS idx_actions_execution_status
    ON actions(execution_status);

CREATE INDEX IF NOT EXISTS idx_actions_applied_at
    ON actions(applied_at);
