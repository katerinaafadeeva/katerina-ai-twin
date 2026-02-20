"""Shared pytest fixtures for PR-3 tests."""

import sqlite3
from pathlib import Path

import pytest

from capabilities.career_os.models import Profile
from core.llm.schemas import ScoreReason, ScoringOutput

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = Path(__file__).parent.parent / "core" / "migrations"

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply all SQL migrations from the migrations directory to *conn*."""
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS _migrations "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    )
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        name = sql_file.name
        if conn.execute("SELECT 1 FROM _migrations WHERE name = ?", (name,)).fetchone():
            continue
        conn.executescript(sql_file.read_text())
        conn.execute("INSERT INTO _migrations (name) VALUES (?)", (name,))
        conn.commit()


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """In-memory SQLite connection with full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# Reusable domain objects
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_profile() -> Profile:
    """Minimal Profile instance for testing sanitize / store functions."""
    return Profile(
        target_roles=("Product Manager",),
        target_seniority=("middle", "senior"),
        work_format=("remote",),
        geo_cities=("Москва",),
        relocation=False,
        salary_min=250_000,
        salary_currency="RUB",
        required_skills=("product management", "analytics"),
        bonus_skills=("SQL", "Jira"),
        negative_signals=("MLM", "cold calling"),
        industries_preferred=("tech", "fintech"),
        industries_excluded=("gambling",),
        languages=("Russian", "English"),
    )


@pytest.fixture()
def sample_scoring_output() -> ScoringOutput:
    """Minimal valid ScoringOutput for store tests."""
    return ScoringOutput(
        score=7,
        reasons=[
            ScoreReason(criterion="role_match", matched=True, note="прямое совпадение")
        ],
        explanation="Хорошее совпадение по роли и формату работы.",
    )
