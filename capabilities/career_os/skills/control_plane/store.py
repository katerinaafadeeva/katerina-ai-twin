"""Persistence layer for control_plane skill.

All functions accept an open sqlite3.Connection as the first argument.
No get_conn() calls here — connection lifecycle is owned by the caller.
No LLM calls — all queries are deterministic SQL.
"""

import logging
import sqlite3
from typing import List, Optional

from capabilities.career_os.skills.apply_policy.store import (
    get_policy,
    get_today_auto_count,
)
from capabilities.career_os.skills.hh_apply.store import get_today_apply_count
from capabilities.career_os.skills.vacancy_ingest_hh.store import get_today_scored_count_by_source

logger = logging.getLogger(__name__)


def get_action_by_id(conn: sqlite3.Connection, action_id: int) -> Optional[dict]:
    """Fetch a single action row by primary key.

    Args:
        conn: Open SQLite connection.
        action_id: Primary key of the actions row.

    Returns:
        Dict with all action columns, or None if not found.
    """
    cursor = conn.execute(
        "SELECT * FROM actions WHERE id = ?",
        (action_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row)


def update_action_status(
    conn: sqlite3.Connection,
    action_id: int,
    new_status: str,
    actor: str = "operator",
) -> bool:
    """Transition an action from 'pending' to a new status.

    Only transitions FROM 'pending' are allowed (idempotent guard).
    Uses WHERE id=? AND status='pending' to prevent race conditions and
    double-click replays — checks rowcount to detect already-transitioned rows.

    Args:
        conn: Open SQLite connection.
        action_id: Primary key of the actions row.
        new_status: Target status ('approved', 'rejected', or 'snoozed').
        actor: Identity of the operator performing the transition.

    Returns:
        True if the row was updated, False if already transitioned (no-op).
    """
    cursor = conn.execute(
        """
        UPDATE actions
           SET status = ?,
               updated_at = datetime('now'),
               actor = ?
         WHERE id = ?
           AND status = 'pending'
        """,
        (new_status, actor, action_id),
    )
    updated = cursor.rowcount == 1
    if updated:
        logger.info(
            "update_action_status: action %d → %s (actor=%s)",
            action_id,
            new_status,
            actor,
        )
    else:
        logger.info(
            "update_action_status: action %d not updated (already transitioned or missing)",
            action_id,
        )
    return updated


def get_today_summary(conn: sqlite3.Connection, apply_daily_cap: int = 0) -> dict:
    """Aggregate stats for the /today operator command.

    Counts are scoped to today's UTC date.
    job_scores uses 'scored_at' (not 'created_at') — verified against schema.

    Args:
        conn: Open SQLite connection.
        apply_daily_cap: APPLY_DAILY_CAP value from config (passed by caller to
            avoid importing config here). Used only for display in the returned dict.

    Returns:
        Dict with keys: total_ingested, total_scored, by_action_type,
        by_status, auto_count, daily_limit, remaining,
        applies_done, apply_daily_cap.
    """
    # Total vacancies ingested today
    row = conn.execute(
        "SELECT COUNT(*) FROM job_raw WHERE date(created_at) = date('now')"
    ).fetchone()
    total_ingested = row[0] if row else 0

    # Total scored today (job_scores uses scored_at)
    row = conn.execute(
        "SELECT COUNT(*) FROM job_scores WHERE date(scored_at) = date('now')"
    ).fetchone()
    total_scored = row[0] if row else 0

    # Actions grouped by action_type, today
    action_types = ["IGNORE", "AUTO_QUEUE", "AUTO_APPLY", "HOLD", "APPROVAL_REQUIRED"]
    by_action_type: dict = {at: 0 for at in action_types}

    rows = conn.execute(
        """
        SELECT action_type, COUNT(*) as cnt
          FROM actions
         WHERE date(created_at) = date('now')
         GROUP BY action_type
        """
    ).fetchall()
    for r in rows:
        at = r[0]
        if at in by_action_type:
            by_action_type[at] = r[1]

    # Actions grouped by status, today
    statuses = ["pending", "approved", "rejected", "snoozed"]
    by_status: dict = {s: 0 for s in statuses}

    rows = conn.execute(
        """
        SELECT status, COUNT(*) as cnt
          FROM actions
         WHERE date(created_at) = date('now')
         GROUP BY status
        """
    ).fetchall()
    for r in rows:
        s = r[0]
        if s in by_status:
            by_status[s] = r[1]

    # Total decisions (all action_types) created today — shown in /today as "Лимит решений"
    row = conn.execute(
        "SELECT COUNT(*) FROM actions WHERE date(created_at) = date('now')"
    ).fetchone()
    decisions_today = row[0] if row else 0

    # auto_count: only AUTO_QUEUE + AUTO_APPLY — used by policy engine internally
    auto_count = get_today_auto_count(conn)
    policy = get_policy(conn)
    daily_limit = policy["daily_limit"]
    remaining = max(0, daily_limit - auto_count)

    applies_done = get_today_apply_count(conn)
    hh_scored_today = get_today_scored_count_by_source(conn, "hh")
    tg_scored_today = get_today_scored_count_by_source(conn, "telegram_forward")

    return {
        "total_ingested": total_ingested,
        "total_scored": total_scored,
        "hh_scored_today": hh_scored_today,
        "tg_scored_today": tg_scored_today,
        "by_action_type": by_action_type,
        "by_status": by_status,
        "decisions_today": decisions_today,
        "auto_count": auto_count,
        "daily_limit": daily_limit,
        "remaining": remaining,
        "applies_done": applies_done,
        "apply_daily_cap": apply_daily_cap,
    }


def get_pending_approvals(conn: sqlite3.Connection) -> List[dict]:
    """List all APPROVAL_REQUIRED actions that are still pending.

    Used by /stats command. Returns most recent first.

    Args:
        conn: Open SQLite connection.

    Returns:
        List of dicts with keys: id, job_raw_id, score, reason, created_at,
        raw_text, hh_vacancy_id.
    """
    rows = conn.execute(
        """
        SELECT a.id, a.job_raw_id, a.score, a.reason, a.created_at,
               jr.raw_text, jr.hh_vacancy_id
          FROM actions a
          JOIN job_raw jr ON jr.id = a.job_raw_id
         WHERE a.action_type = 'APPROVAL_REQUIRED'
           AND a.status = 'pending'
         ORDER BY a.created_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_policy_display(conn: sqlite3.Connection) -> dict:
    """Policy thresholds and remaining daily capacity for /limits command.

    Args:
        conn: Open SQLite connection.

    Returns:
        Dict with keys: threshold_low, threshold_high, daily_limit,
        today_auto_count, remaining.
    """
    policy = get_policy(conn)
    auto_count = get_today_auto_count(conn)
    daily_limit = policy["daily_limit"]
    remaining = max(0, daily_limit - auto_count)

    return {
        "threshold_low": policy["threshold_low"],
        "threshold_high": policy["threshold_high"],
        "daily_limit": daily_limit,
        "today_auto_count": auto_count,
        "remaining": remaining,
    }
