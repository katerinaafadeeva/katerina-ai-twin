"""Tests for score cache by hh_vacancy_id."""
import sqlite3
import pytest
from capabilities.career_os.skills.match_scoring.store import get_existing_score_by_hh_vacancy_id


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE job_raw (
            id INTEGER PRIMARY KEY,
            hh_vacancy_id TEXT,
            raw_text TEXT,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE job_scores (
            id INTEGER PRIMARY KEY,
            job_raw_id INTEGER,
            score INTEGER,
            scored_at TEXT DEFAULT (datetime('now'))
        )
    """)
    return conn


def test_score_cache_hit():
    conn = _setup_db()
    conn.execute("INSERT INTO job_raw (id, hh_vacancy_id, raw_text, source) VALUES (1, 'vac123', 'text', 'hh')")
    conn.execute("INSERT INTO job_scores (job_raw_id, score) VALUES (1, 7)")
    result = get_existing_score_by_hh_vacancy_id(conn, 'vac123')
    assert result == 7


def test_score_cache_miss():
    conn = _setup_db()
    conn.execute("INSERT INTO job_raw (id, hh_vacancy_id, raw_text, source) VALUES (1, 'vac999', 'text', 'hh')")
    result = get_existing_score_by_hh_vacancy_id(conn, 'vac999')
    assert result is None


def test_score_cache_none_vacancy_id():
    conn = _setup_db()
    result = get_existing_score_by_hh_vacancy_id(conn, None)
    assert result is None


def test_score_cache_empty_vacancy_id():
    conn = _setup_db()
    result = get_existing_score_by_hh_vacancy_id(conn, "")
    assert result is None
