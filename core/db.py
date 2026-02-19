import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "data/career.db")

DDL = """
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
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(DDL)
        # seed default policy row if missing
        conn.execute(
            "INSERT INTO policy (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM policy WHERE id = 1)"
        )
