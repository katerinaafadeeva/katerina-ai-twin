import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent


def apply_all(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name       TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        name = sql_file.name
        if conn.execute("SELECT 1 FROM _migrations WHERE name = ?", (name,)).fetchone():
            continue
        logger.info("Applying migration: %s", name)
        conn.executescript(sql_file.read_text())
        conn.execute("INSERT INTO _migrations (name) VALUES (?)", (name,))
        conn.commit()
        logger.info("Applied: %s", name)
