"""Tests: apply cap counts only done status, not skipped/failed."""
import sqlite3
import pytest
from capabilities.career_os.skills.hh_apply.store import get_today_apply_count


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE apply_runs (
            id INTEGER PRIMARY KEY,
            action_id INTEGER,
            status TEXT,
            finished_at TEXT DEFAULT (datetime('now'))
        )
    """)
    return conn


def test_apply_cap_counts_only_done():
    conn = _setup_db()
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (1, 'done')")
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (2, 'done')")
    assert get_today_apply_count(conn) == 2


def test_skipped_not_counted_in_apply_cap():
    conn = _setup_db()
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (1, 'already_applied')")
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (2, 'failed')")
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (3, 'manual_required')")
    assert get_today_apply_count(conn) == 0


def test_failed_not_counted_in_apply_cap():
    conn = _setup_db()
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (1, 'done')")
    conn.execute("INSERT INTO apply_runs (action_id, status) VALUES (2, 'failed')")
    assert get_today_apply_count(conn) == 1
