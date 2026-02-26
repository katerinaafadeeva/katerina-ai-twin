"""Persistence for hh_apply skill.

All functions accept sqlite3.Connection. No get_conn() inside — caller owns lifecycle.
No LLM calls — pure SQL.

Execution status values:
  pending         — not yet attempted (NULL or 'pending' in DB)
  done            — application submitted successfully
  already_applied — already applied before this cycle
  manual_required — apply button absent; operator must act manually
  captcha         — captcha detected; batch stopped
  session_expired — auth state expired; re-bootstrap required
  failed          — unexpected error (will retry up to 3 times)
"""

import logging
import sqlite3
from typing import List, Optional

logger = logging.getLogger(__name__)

# Max attempts before giving up on a task
MAX_ATTEMPTS = 3

# HH vacancy URL pattern
_HH_VACANCY_URL = "https://hh.ru/vacancy/{}"


def get_pending_apply_tasks(conn: sqlite3.Connection, limit: int = 5) -> List[dict]:
    """Return AUTO_APPLY actions ready for browser execution.

    Criteria:
    - action_type = 'AUTO_APPLY'
    - status = 'pending' (not yet approved/rejected/snoozed by operator)
    - execution_status IS NULL OR execution_status = 'pending' OR execution_status = 'failed'
    - execution_attempts < MAX_ATTEMPTS (3)
    - job_raw has hh_vacancy_id (needed to construct apply URL)

    Ordered by created_at ASC (oldest first).
    """
    rows = conn.execute(
        """
        SELECT
            a.id            AS action_id,
            a.job_raw_id,
            a.correlation_id,
            a.execution_attempts,
            jr.hh_vacancy_id,
            cl.letter_text  AS cover_letter
        FROM actions a
        JOIN job_raw jr ON jr.id = a.job_raw_id
        LEFT JOIN cover_letters cl ON cl.action_id = a.id
        WHERE a.action_type = 'AUTO_APPLY'
          AND a.status = 'pending'
          AND (a.execution_status IS NULL
               OR a.execution_status = 'pending'
               OR a.execution_status = 'failed')
          AND COALESCE(a.execution_attempts, 0) < ?
          AND jr.hh_vacancy_id IS NOT NULL
        ORDER BY a.created_at ASC
        LIMIT ?
        """,
        (MAX_ATTEMPTS, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def update_action_execution(
    conn: sqlite3.Connection,
    action_id: int,
    execution_status: str,
    error: Optional[str] = None,
    applied_at: Optional[str] = None,
    apply_url: Optional[str] = None,
) -> None:
    """Update execution tracking fields and increment attempts counter."""
    conn.execute(
        """
        UPDATE actions
        SET execution_status    = ?,
            execution_error     = ?,
            applied_at          = ?,
            hh_apply_url        = ?,
            execution_attempts  = COALESCE(execution_attempts, 0) + 1
        WHERE id = ?
        """,
        (execution_status, error, applied_at, apply_url, action_id),
    )
    logger.debug(
        "Action %d execution_status=%s attempts+1",
        action_id,
        execution_status,
    )


def get_today_apply_count(conn: sqlite3.Connection) -> int:
    """Count successful applies today (UTC). Used to enforce APPLY_DAILY_CAP."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM actions
        WHERE execution_status = 'done'
          AND date(applied_at) = date('now')
        """
    ).fetchone()
    return row[0] if row else 0


def was_apply_cap_notification_sent_today(conn: sqlite3.Connection) -> bool:
    """Check if apply.cap_reached event was emitted today (UTC)."""
    row = conn.execute(
        """
        SELECT 1 FROM events
        WHERE event_name = 'apply.cap_reached'
          AND date(created_at) = date('now')
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def get_hh_vacancy_url(hh_vacancy_id: str) -> str:
    """Construct HH.ru vacancy URL from vacancy ID string."""
    return _HH_VACANCY_URL.format(hh_vacancy_id)
