-- Migration 008: apply_runs — execution log (separation decision vs execution)
--
-- actions table = immutable DECISION log (what policy engine decided).
-- apply_runs table = EXECUTION log (what browser did, one row per attempt).
--
-- Separation rationale:
-- - actions.status tracks operator approval (pending/approved/rejected/snoozed)
-- - apply_runs.status tracks browser result (done/failed/captcha/...)
-- - Multiple retry attempts each get their own row → full history, no data loss
-- - Easier to extend: multiple resumes, multiple channels, screenshots per attempt

CREATE TABLE IF NOT EXISTS apply_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id   INTEGER NOT NULL REFERENCES actions(id),
    attempt     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,         -- done/already_applied/manual_required/captcha/session_expired/failed
    error       TEXT,                  -- error message (truncated to 500 chars)
    apply_url   TEXT,                  -- HH.ru vacancy URL used in this attempt
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    UNIQUE(action_id, attempt)         -- one row per (action, attempt number)
);

CREATE INDEX IF NOT EXISTS idx_apply_runs_action   ON apply_runs(action_id);
CREATE INDEX IF NOT EXISTS idx_apply_runs_status   ON apply_runs(status);
CREATE INDEX IF NOT EXISTS idx_apply_runs_finished ON apply_runs(finished_at);
