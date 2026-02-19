import hashlib
from typing import Tuple

from core.db import get_conn
from core.events import emit


def _canonical_key(text: str) -> str:
    normalized = text.strip().lower()[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def ingest(raw_text: str, source: str, source_message_id: str) -> Tuple[int, bool]:
    """Insert job_raw if not exists. Returns (job_raw_id, is_new)."""
    canonical_key = _canonical_key(raw_text)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO job_raw (raw_text, source, source_message_id, canonical_key)
            VALUES (?, ?, ?, ?)
            """,
            (raw_text, source, source_message_id, canonical_key),
        )
        if cur.rowcount == 1:
            job_raw_id = cur.lastrowid
            is_new = True
        else:
            row = conn.execute(
                "SELECT id FROM job_raw WHERE source = ? AND source_message_id = ?",
                (source, source_message_id),
            ).fetchone()
            job_raw_id = row["id"]
            is_new = False

    if is_new:
        emit("vacancy.ingested", {"job_raw_id": job_raw_id})

    return job_raw_id, is_new
