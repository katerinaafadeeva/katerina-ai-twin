"""Persistent JSONL log for every apply attempt and cover letter sent.

Writes one JSON line per apply event to logs/apply_log.jsonl.
The file is gitignored (personal data) — it accumulates locally over time
and provides a human-readable audit trail: what was applied to, what letter
was sent, and what the outcome was.

Usage (from apply worker):
    from core.apply_logger import log_apply_event
    log_apply_event(
        job_raw_id=task["job_raw_id"],
        hh_vacancy_id=task["hh_vacancy_id"],
        vacancy_title="...",
        apply_url="https://hh.ru/vacancy/...",
        status="done",
        letter_status="sent_popup",
        cover_letter_text="...",
        score=8,
        action_id=42,
    )
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "apply_log.jsonl")


def log_apply_event(
    job_raw_id: int,
    hh_vacancy_id: str,
    vacancy_title: str,
    apply_url: str,
    status: str,
    letter_status: str = "",
    cover_letter_text: str = "",
    score: int = 0,
    action_id: int = 0,
) -> None:
    """Append one apply event to logs/apply_log.jsonl.

    Never raises — failures are logged and silently ignored so the apply
    worker is not affected by logging errors.
    """
    try:
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "action_id": action_id,
            "job_raw_id": job_raw_id,
            "hh_vacancy_id": hh_vacancy_id,
            "title": vacancy_title or "",
            "url": apply_url,
            "status": status,
            "letter_status": letter_status or "",
            "score": score or 0,
            "cover_letter_len": len(cover_letter_text) if cover_letter_text else 0,
            "cover_letter": cover_letter_text or "",
        }
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("apply_logger: failed to write log entry: %s", exc)
