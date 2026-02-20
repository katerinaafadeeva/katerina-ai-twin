import logging
import os
import sqlite3

from core.migrations import migrate

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/career.db")


def get_conn() -> sqlite3.Connection:
    logger.debug("Opening DB connection: %s", DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_conn_from_path(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        migrate.apply_all(conn)
