"""Text formatting utilities for control_plane skill.

Pure functions — no DB access, no LLM calls.
Used by both handlers.py (stats) and match_scoring/worker.py (notifications).
"""

from typing import Tuple


def extract_vacancy_title(raw_text: str) -> Tuple[str, str]:
    """Extract (position, company) from raw_text.

    Looks for lines starting with "Позиция:" and "Компания:".
    Falls back to the first 250 chars of raw_text as the position if neither
    field is found — ensures the operator always sees meaningful context.

    Args:
        raw_text: Raw vacancy text as stored in job_raw.raw_text.

    Returns:
        Tuple of (position, company). Either may be empty string if not found.
        Position is never empty — falls back to first 250 chars of raw_text.
    """
    position = ""
    company = ""

    for line in raw_text.splitlines():
        line = line.strip()
        if not position and line.startswith("Позиция:"):
            position = line.split(":", 1)[1].strip()[:60]
        elif not company and line.startswith("Компания:"):
            company = line.split(":", 1)[1].strip()[:40]
        if position and company:
            break

    if not position:
        # Fallback: show first 250 chars of raw text so operator has context
        fallback = raw_text.strip()[:250].replace("\n", " ")
        position = fallback or "Вакансия"

    return position, company
