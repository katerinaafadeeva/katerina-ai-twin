"""Persistence for HH vacancy ingestion.

All functions accept sqlite3.Connection. No get_conn() inside.
No LLM calls — all queries are deterministic SQL.
"""

import hashlib
import logging
import sqlite3
from typing import Tuple

logger = logging.getLogger(__name__)


def compute_canonical_key(text: str) -> str:
    """Generate canonical key for cross-source dedup (TG↔HH).

    Uses same algorithm as vacancy_ingest_telegram.handler for compatibility.
    SHA256 of first 200 chars of lowercased, stripped text → 16-char hex prefix.
    """
    normalized = text.strip().lower()[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# Keep internal alias for backward-compat within this module
_canonical_key = compute_canonical_key


def is_hh_vacancy_ingested(conn: sqlite3.Connection, hh_vacancy_id: str) -> bool:
    """Check if HH vacancy was already ingested by its HH ID.

    Fast O(1) lookup via idx_job_raw_hh_id index.
    """
    row = conn.execute(
        "SELECT 1 FROM job_raw WHERE hh_vacancy_id = ? LIMIT 1",
        (hh_vacancy_id,),
    ).fetchone()
    return row is not None


def is_canonical_key_ingested(conn: sqlite3.Connection, canonical_key: str) -> bool:
    """Check if a vacancy with the same canonical key already exists (any source).

    Catches cross-source duplicates: same vacancy forwarded via TG then found on HH.
    """
    row = conn.execute(
        "SELECT 1 FROM job_raw WHERE canonical_key = ? LIMIT 1",
        (canonical_key,),
    ).fetchone()
    return row is not None


def get_today_scored_count(conn: sqlite3.Connection) -> int:
    """Count vacancies scored today (UTC date). Used for daily LLM cap enforcement."""
    row = conn.execute(
        "SELECT COUNT(*) FROM job_scores WHERE date(scored_at) = date('now')"
    ).fetchone()
    return row[0] if row else 0


def was_scoring_cap_notification_sent_today(conn: sqlite3.Connection) -> bool:
    """Check if a scoring.cap_reached event was emitted today.

    Prevents duplicate Telegram notifications about the daily cap.
    """
    row = conn.execute(
        """
        SELECT 1 FROM events
         WHERE event_name = 'scoring.cap_reached'
           AND date(created_at) = date('now')
         LIMIT 1
        """
    ).fetchone()
    return row is not None


def save_hh_vacancy(
    conn: sqlite3.Connection,
    hh_vacancy_id: str,
    raw_text: str,
    source_url: str,
) -> Tuple[int, bool]:
    """Save HH vacancy to job_raw. Returns (job_raw_id, is_new).

    Dedup by (source, source_message_id) via UNIQUE index.
    Also sets hh_vacancy_id for fast lookups.
    source_url is stored as correlation info (not a DB column — included in raw_text footer).
    """
    source_message_id = f"hh_{hh_vacancy_id}"
    key = _canonical_key(raw_text)

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO job_raw
            (raw_text, source, source_message_id, canonical_key, hh_vacancy_id)
        VALUES (?, 'hh', ?, ?, ?)
        """,
        (raw_text, source_message_id, key, hh_vacancy_id),
    )

    if cursor.rowcount == 1:
        logger.debug("Saved new HH vacancy hh_id=%s job_raw_id=%d", hh_vacancy_id, cursor.lastrowid)
        return cursor.lastrowid, True

    # Already exists — find existing row
    row = conn.execute(
        "SELECT id FROM job_raw WHERE source = 'hh' AND source_message_id = ?",
        (source_message_id,),
    ).fetchone()
    return (row["id"] if row else 0), False
