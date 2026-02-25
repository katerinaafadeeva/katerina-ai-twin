"""Persistence for cover letter skill.

All functions accept sqlite3.Connection. No get_conn() inside.
No LLM calls — all queries are deterministic SQL.
"""

import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


def save_cover_letter(
    conn: sqlite3.Connection,
    job_raw_id: int,
    action_id: int,
    letter_text: str,
    model: str,
    prompt_version: str,
    is_fallback: bool = False,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> int:
    """Save cover letter to DB. Returns row-id (0 if already exists).

    Uses INSERT OR IGNORE for idempotency (UNIQUE on job_raw_id, action_id).
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO cover_letters
            (job_raw_id, action_id, letter_text, model, prompt_version,
             is_fallback, input_tokens, output_tokens, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_raw_id, action_id, letter_text, model, prompt_version,
            1 if is_fallback else 0, input_tokens, output_tokens, cost_usd,
        ),
    )
    rowid = cursor.lastrowid if cursor.rowcount > 0 else 0
    if rowid:
        logger.debug(
            "Saved cover letter job_raw_id=%d action_id=%d is_fallback=%s",
            job_raw_id, action_id, is_fallback,
        )
    else:
        logger.debug(
            "Cover letter already exists for job_raw_id=%d action_id=%d — skipped",
            job_raw_id, action_id,
        )
    return rowid


def get_cover_letter_for_action(
    conn: sqlite3.Connection, action_id: int
) -> Optional[dict]:
    """Fetch cover letter by action_id. Returns dict or None."""
    row = conn.execute(
        "SELECT * FROM cover_letters WHERE action_id = ? LIMIT 1",
        (action_id,),
    ).fetchone()
    return dict(row) if row else None


def get_cover_letter_for_job(
    conn: sqlite3.Connection, job_raw_id: int
) -> Optional[dict]:
    """Fetch most recent cover letter for a job_raw_id. Returns dict or None."""
    row = conn.execute(
        "SELECT * FROM cover_letters WHERE job_raw_id = ? ORDER BY created_at DESC LIMIT 1",
        (job_raw_id,),
    ).fetchone()
    return dict(row) if row else None


def get_today_cover_letter_count(conn: sqlite3.Connection) -> int:
    """Count LLM-generated (non-fallback) cover letters today (UTC). For daily cap."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM cover_letters
        WHERE is_fallback = 0
          AND date(created_at) = date('now')
        """
    ).fetchone()
    return row[0] if row else 0


def was_cover_letter_cap_notification_sent_today(conn: sqlite3.Connection) -> bool:
    """Check if cover_letter.cap_reached event was emitted today (UTC)."""
    row = conn.execute(
        """
        SELECT 1 FROM events
        WHERE event_name = 'cover_letter.cap_reached'
          AND date(created_at) = date('now')
        LIMIT 1
        """
    ).fetchone()
    return row is not None
