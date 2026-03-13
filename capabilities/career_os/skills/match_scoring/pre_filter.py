"""Pre-filter for match_scoring: keyword/regex reject before LLM call.

Returns (should_skip, reason) for obvious mismatches to avoid LLM costs.
"""

import re

_REJECT_PATTERNS = [
    r'\bстажёр\b',
    r'\bстажер\b',
    r'\bintern\b',
    r'\bjunior\b(?!.*(?:product|project|pm|менеджер\s+проект))',
    r'\bводитель\b',
    r'\bкурьер\b',
    r'\bгрузчик\b',
    r'\bпродавец\b',
    r'\bкассир\b',
    r'\bповар\b',
    r'\bуборщик\b',
    r'\bохранник\b',
]

_REJECT_RE = re.compile('|'.join(_REJECT_PATTERNS), re.IGNORECASE)


def should_skip_scoring(vacancy_text: str) -> tuple:
    """Returns (should_skip, reason) — True if vacancy is obvious mismatch."""
    if not vacancy_text or len(vacancy_text.strip()) < 50:
        return True, "too_short"

    match = _REJECT_RE.search(vacancy_text)
    if match:
        return True, f"keyword_reject:{match.group()}"

    return False, ""
