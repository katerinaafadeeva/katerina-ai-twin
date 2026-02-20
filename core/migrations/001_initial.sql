CREATE TABLE IF NOT EXISTS job_raw (
    id                INTEGER PRIMARY KEY,
    raw_text          TEXT,
    source            TEXT,
    source_message_id TEXT,
    canonical_key     TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    event_name   TEXT,
    payload_json TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY,
    job_raw_id  INTEGER,
    action_type TEXT,
    status      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS policy (
    id              INTEGER PRIMARY KEY,
    threshold_low   INTEGER DEFAULT 5,
    threshold_high  INTEGER DEFAULT 7,
    daily_limit     INTEGER DEFAULT 40
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_raw_dedup
    ON job_raw (source, source_message_id);

INSERT INTO policy (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM policy WHERE id = 1);
