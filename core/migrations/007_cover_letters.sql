CREATE TABLE IF NOT EXISTS cover_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_raw_id      INTEGER NOT NULL REFERENCES job_raw(id),
    action_id       INTEGER REFERENCES actions(id),
    letter_text     TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    is_fallback     BOOLEAN NOT NULL DEFAULT 0,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(job_raw_id, action_id)
);
CREATE INDEX IF NOT EXISTS idx_cover_letters_job ON cover_letters(job_raw_id);
CREATE INDEX IF NOT EXISTS idx_cover_letters_action ON cover_letters(action_id);
