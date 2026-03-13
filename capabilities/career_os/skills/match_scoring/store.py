"""Score persistence for match_scoring skill.

All functions accept an open sqlite3.Connection as the first argument.
No get_conn() calls here — connection lifecycle is owned by the caller (worker).
"""

import json
import logging
import sqlite3
from typing import List, Optional

from core.llm.schemas import ScoringOutput

logger = logging.getLogger(__name__)


def get_unscored_vacancies(
    conn: sqlite3.Connection,
    scorer_version: str = "v1",
) -> List[dict]:
    """Return vacancies that have not yet been scored by *scorer_version*.

    Uses a LEFT JOIN on job_scores to find rows with no matching score record.
    Ordered oldest-first so earlier submissions are processed first.

    Args:
        conn: Open SQLite connection (row_factory = sqlite3.Row expected).
        scorer_version: The scorer version string to check against (default "v1").

    Returns:
        List of dicts with keys: id, raw_text, source, created_at.
    """
    cursor = conn.execute(
        """
        SELECT jr.id, jr.raw_text, jr.source, jr.created_at, jr.hh_vacancy_id
        FROM job_raw jr
        LEFT JOIN job_scores js
            ON jr.id = js.job_raw_id AND js.scorer_version = ?
        WHERE js.id IS NULL
        ORDER BY
            CASE WHEN jr.source = 'telegram_forward' THEN 0 ELSE 1 END,
            jr.created_at ASC
        """,
        (scorer_version,),
    )
    rows = cursor.fetchall()
    result = [dict(row) for row in rows]
    logger.debug("get_unscored_vacancies: found %d unscored rows", len(result))
    return result


def save_score(
    conn: sqlite3.Connection,
    job_raw_id: int,
    result: ScoringOutput,
    profile_hash: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    scorer_version: str = "v1",
) -> int:
    """Persist a scoring result idempotently.

    Uses INSERT OR IGNORE so that if a score for the same (job_raw_id,
    scorer_version) pair already exists the insert is silently skipped.

    Args:
        conn: Open SQLite connection.
        job_raw_id: FK to job_raw.id.
        result: Validated ScoringOutput from the LLM.
        profile_hash: Short hash of the Profile used (from Profile.content_hash()).
        model: Anthropic model ID used for scoring.
        prompt_version: Prompt version string (e.g. "scoring_v1").
        input_tokens: Input token count (0 if tracked separately via llm.call event).
        output_tokens: Output token count (0 if tracked separately).
        cost_usd: Estimated cost in USD (0.0 if tracked separately).
        scorer_version: Scorer version string (default "v1").

    Returns:
        Row-id of the inserted row, or 0 if the row already existed (skipped).
    """
    reasons_json = json.dumps(
        [r.model_dump() for r in result.reasons],
        ensure_ascii=False,
    )

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO job_scores
            (job_raw_id, score, reasons_json, explanation,
             model, prompt_version, input_tokens, output_tokens,
             cost_usd, profile_hash, scorer_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_raw_id,
            result.score,
            reasons_json,
            result.explanation,
            model,
            prompt_version,
            input_tokens,
            output_tokens,
            cost_usd,
            profile_hash,
            scorer_version,
        ),
    )

    rowid = cursor.lastrowid if cursor.rowcount > 0 else 0
    if rowid:
        logger.info(
            "save_score: persisted score",
            extra={
                "job_raw_id": job_raw_id,
                "score": result.score,
                "scorer_version": scorer_version,
                "rowid": rowid,
            },
        )
    else:
        logger.debug(
            "save_score: skipped (already scored)",
            extra={"job_raw_id": job_raw_id, "scorer_version": scorer_version},
        )

    return rowid


def get_existing_score_by_hh_vacancy_id(
    conn: sqlite3.Connection,
    hh_vacancy_id: str,
) -> Optional[int]:
    """Return score if a vacancy with this hh_vacancy_id was already scored.

    Used for cache hits: if the same HH vacancy appears twice (e.g. re-ingested),
    skip LLM and reuse the previous score.

    Args:
        conn: Open SQLite connection.
        hh_vacancy_id: HH.ru vacancy ID string.

    Returns:
        Integer score, or None if not yet scored.
    """
    if not hh_vacancy_id:
        return None
    row = conn.execute(
        """SELECT js.score FROM job_scores js
           JOIN job_raw jr ON jr.id = js.job_raw_id
           WHERE jr.hh_vacancy_id = ?
           ORDER BY js.scored_at DESC LIMIT 1""",
        (hh_vacancy_id,)
    ).fetchone()
    return row[0] if row else None


def get_score(
    conn: sqlite3.Connection,
    job_raw_id: int,
    scorer_version: str = "v1",
) -> Optional[dict]:
    """Fetch the score record for a given vacancy and scorer version.

    Args:
        conn: Open SQLite connection.
        job_raw_id: FK to job_raw.id.
        scorer_version: Scorer version string (default "v1").

    Returns:
        Dict of the job_scores row, or None if not yet scored.
    """
    cursor = conn.execute(
        """
        SELECT * FROM job_scores
        WHERE job_raw_id = ? AND scorer_version = ?
        LIMIT 1
        """,
        (job_raw_id, scorer_version),
    )
    row = cursor.fetchone()
    return dict(row) if row else None
