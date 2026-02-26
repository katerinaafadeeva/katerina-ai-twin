"""Persistence for hh_apply skill.

All functions accept sqlite3.Connection. No get_conn() inside — caller owns lifecycle.
No LLM calls — pure SQL.

Schema separation:
  actions    = DECISION log (policy engine output, immutable after creation)
  apply_runs = EXECUTION log (one row per browser attempt, full history)

apply_runs.status values:
  done            — application submitted successfully
  already_applied — already applied before this cycle (not a retry candidate)
  manual_required — apply button absent; operator must act manually
  captcha         — captcha detected; batch stopped
  session_expired — auth state expired; re-bootstrap required
  failed          — unexpected error (will be retried up to MAX_ATTEMPTS)
"""

import logging
import sqlite3
from typing import List, Optional

logger = logging.getLogger(__name__)

# Max browser attempts per action before giving up
MAX_ATTEMPTS = 3

# HH vacancy URL pattern
_HH_VACANCY_URL = "https://hh.ru/vacancy/{}"


def get_pending_apply_tasks(conn: sqlite3.Connection, limit: int = 5) -> List[dict]:
    """Return AUTO_APPLY actions ready for browser execution.

    Criteria:
    - action_type = 'AUTO_APPLY'
    - status = 'pending' (not yet operator-approved/rejected/snoozed)
    - No successful apply_run yet (execution_status != 'done')
    - Attempt count in apply_runs < MAX_ATTEMPTS
    - job_raw has hh_vacancy_id (needed to construct apply URL)

    Returns attempt_count in each row so caller can compute next attempt number.
    Ordered by created_at ASC (oldest first).
    """
    rows = conn.execute(
        """
        SELECT
            a.id            AS action_id,
            a.job_raw_id,
            a.correlation_id,
            jr.hh_vacancy_id,
            cl.letter_text  AS cover_letter,
            COALESCE(r.attempt_count, 0) AS attempt_count
        FROM actions a
        JOIN job_raw jr ON jr.id = a.job_raw_id
        LEFT JOIN cover_letters cl ON cl.action_id = a.id
        LEFT JOIN (
            SELECT action_id, COUNT(*) AS attempt_count
            FROM apply_runs
            GROUP BY action_id
        ) r ON r.action_id = a.id
        WHERE a.action_type = 'AUTO_APPLY'
          AND a.status = 'pending'
          AND jr.hh_vacancy_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM apply_runs ar
              WHERE ar.action_id = a.id
                AND ar.status IN ('done', 'done_without_letter')
          )
          AND NOT EXISTS (
              SELECT 1 FROM apply_runs ar
              WHERE ar.action_id = a.id
                AND ar.status IN ('already_applied', 'manual_required',
                                  'captcha', 'session_expired')
          )
          AND COALESCE(r.attempt_count, 0) < ?
        ORDER BY a.created_at ASC
        LIMIT ?
        """,
        (MAX_ATTEMPTS, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def save_apply_run(
    conn: sqlite3.Connection,
    action_id: int,
    attempt: int,
    status: str,
    error: Optional[str] = None,
    apply_url: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> int:
    """Insert a new apply_run record. Returns row-id.

    started_at defaults to datetime('now') in the DB column definition.
    finished_at should be set to the completion time.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO apply_runs
            (action_id, attempt, status, error, apply_url, finished_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (action_id, attempt, status, error, apply_url, finished_at),
    )
    rowid = cursor.lastrowid if cursor.rowcount > 0 else 0
    logger.debug(
        "apply_run saved: action_id=%d attempt=%d status=%s rowid=%d",
        action_id, attempt, status, rowid,
    )
    return rowid


def get_today_apply_count(conn: sqlite3.Connection) -> int:
    """Count successful applies today (UTC). Used to enforce APPLY_DAILY_CAP.

    Counts apply_runs with status='done' and date(finished_at)=today.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM apply_runs
        WHERE status IN ('done', 'done_without_letter')
          AND date(finished_at) = date('now')
        """
    ).fetchone()
    return row[0] if row else 0


def get_attempt_count(conn: sqlite3.Connection, action_id: int) -> int:
    """Count existing apply_runs for a given action (all statuses)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM apply_runs WHERE action_id = ?",
        (action_id,),
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
