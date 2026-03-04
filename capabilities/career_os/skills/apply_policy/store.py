"""Persistence layer for apply_policy skill.

All functions accept an open sqlite3.Connection as the first argument.
No get_conn() calls here — connection lifecycle is owned by the caller.
"""

import logging
import sqlite3
from typing import Optional

from capabilities.career_os.skills.apply_policy.engine import ActionType, PolicyDecision

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD_LOW = 5
_DEFAULT_THRESHOLD_HIGH = 7
_DEFAULT_DAILY_LIMIT = 40


def get_policy(conn: sqlite3.Connection) -> dict:
    """Read policy configuration from DB (row id=1).

    Returns defaults if the row is missing (threshold_low=5, threshold_high=7,
    daily_limit=40).

    Args:
        conn: Open SQLite connection.

    Returns:
        Dict with keys: id, threshold_low, threshold_high, daily_limit.
    """
    cursor = conn.execute(
        "SELECT id, threshold_low, threshold_high, daily_limit FROM policy WHERE id = 1"
    )
    row = cursor.fetchone()
    if row:
        return dict(row)
    logger.warning("Policy row id=1 not found — using defaults")
    return {
        "id": 1,
        "threshold_low": _DEFAULT_THRESHOLD_LOW,
        "threshold_high": _DEFAULT_THRESHOLD_HIGH,
        "daily_limit": _DEFAULT_DAILY_LIMIT,
    }


def get_today_auto_count(conn: sqlite3.Connection) -> int:
    """Count AUTO_QUEUE + AUTO_APPLY actions recorded today (UTC date).

    Both action types consume the daily limit.

    Args:
        conn: Open SQLite connection.

    Returns:
        Integer count of qualifying actions for today.
    """
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM actions
        WHERE action_type IN (?, ?)
          AND date(created_at) = date('now')
        """,
        (ActionType.AUTO_QUEUE.value, ActionType.AUTO_APPLY.value),
    )
    row = cursor.fetchone()
    count = row[0] if row else 0
    logger.debug("get_today_auto_count: %d", count)
    return count


def get_today_hold_count(conn: sqlite3.Connection) -> int:
    """Count HOLD actions recorded today (UTC date).

    Args:
        conn: Open SQLite connection.

    Returns:
        Integer count of HOLD actions for today.
    """
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM actions
        WHERE action_type = ?
          AND date(created_at) = date('now')
        """,
        (ActionType.HOLD.value,),
    )
    row = cursor.fetchone()
    count = row[0] if row else 0
    logger.debug("get_today_hold_count: %d", count)
    return count


def was_hold_notification_sent_today(conn: sqlite3.Connection) -> bool:
    """Check whether a policy.hold_summary event was emitted today (UTC date).

    Used to send at most one HOLD summary notification per calendar day.

    Args:
        conn: Open SQLite connection.

    Returns:
        True if a policy.hold_summary event exists for today, False otherwise.
    """
    cursor = conn.execute(
        """
        SELECT 1 FROM events
        WHERE event_name = 'policy.hold_summary'
          AND date(created_at) = date('now')
        LIMIT 1
        """,
    )
    found = cursor.fetchone() is not None
    logger.debug("was_hold_notification_sent_today: %s", found)
    return found


def save_action(
    conn: sqlite3.Connection,
    job_raw_id: int,
    decision: PolicyDecision,
    score: int,
    actor: str = "policy_engine",
    correlation_id: Optional[str] = None,
) -> int:
    """Persist a policy decision to the actions table.

    Writes action_type, status='pending', and the extended columns added in
    migration 004 (score, reason, actor, correlation_id).

    Args:
        conn: Open SQLite connection.
        job_raw_id: FK to job_raw.id.
        decision: PolicyDecision returned by evaluate_policy().
        score: Vacancy score (0–10) for audit purposes.
        actor: Identity of the component that triggered the action (default "policy_engine").
        correlation_id: Optional trace ID flowing from the original ingest event.

    Returns:
        Row-id of the newly inserted actions row.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO actions
            (job_raw_id, action_type, status, score, reason, actor, correlation_id)
        VALUES (?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            job_raw_id,
            decision.action_type.value,
            score,
            decision.reason,
            actor,
            correlation_id,
        ),
    )
    rowid = cursor.lastrowid if cursor.rowcount > 0 else 0
    if rowid:
        logger.info(
            "save_action: persisted action",
            extra={
                "job_raw_id": job_raw_id,
                "action_type": decision.action_type.value,
                "score": score,
                "rowid": rowid,
            },
        )
    else:
        logger.debug(
            "save_action: skipped (duplicate job_raw_id=%d action_type=%s)",
            job_raw_id,
            decision.action_type.value,
        )
    return rowid
