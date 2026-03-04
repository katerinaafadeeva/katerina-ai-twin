-- Migration 010: deduplicate actions table
--
-- Problem: duplicate (job_raw_id, action_type) rows can appear when the scoring
-- worker runs concurrent cycles or when HH ingest and TG ingest race each other.
-- The scoring worker already has an in-memory dedup guard, but the DB itself had
-- no constraint — existing duplicates could accumulate over time.
--
-- This migration:
--   1. Removes existing duplicate rows, keeping the earliest row per pair.
--   2. Adds a UNIQUE INDEX to prevent future duplicates.

-- Step 1: remove duplicates (keep lowest id per (job_raw_id, action_type))
DELETE FROM actions
WHERE id NOT IN (
    SELECT MIN(id)
    FROM actions
    GROUP BY job_raw_id, action_type
);

-- Step 2: add unique index so future inserts with INSERT OR IGNORE are safe
CREATE UNIQUE INDEX IF NOT EXISTS idx_actions_job_raw_dedup
    ON actions(job_raw_id, action_type);
