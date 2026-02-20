CREATE TABLE IF NOT EXISTS job_scores (
    id              INTEGER PRIMARY KEY,
    job_raw_id      INTEGER NOT NULL REFERENCES job_raw(id),
    score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),
    reasons_json    TEXT NOT NULL,
    explanation     TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    profile_hash    TEXT NOT NULL,
    scorer_version  TEXT NOT NULL DEFAULT 'v1',
    scored_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_raw_id, scorer_version)
);
