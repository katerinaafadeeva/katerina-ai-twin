import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# --- Regex patterns compiled once at import ---

# Zero-width and invisible characters — common prompt injection vectors
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2028-\u202f\u2060\ufeff]")

# Control characters except \n (U+000A)
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")

# Three or more consecutive newlines → two
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")

# --- Profile field allowlist ---
# Explicit allowlist: anything NOT listed is excluded from LLM input.
# This is an intentional security boundary — add fields only after review.
_PROFILE_ALLOWED_FIELDS = frozenset(
    {
        "target_roles",
        "target_seniority",
        "work_format",
        "geo_cities",
        "relocation",
        "required_skills",
        "bonus_skills",
        "negative_signals",
        "industries_preferred",
        "industries_excluded",
        "languages",
    }
)


def sanitize_for_llm(text: str, max_chars: int = 2000) -> str:
    """Sanitize untrusted vacancy text before sending to LLM.

    Steps:
    1. Remove zero-width / invisible characters (injection vectors).
    2. Remove control characters except newline.
    3. Truncate to max_chars.
    4. Normalize 3+ consecutive newlines to 2.
    5. Strip leading/trailing whitespace.
    """
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text[:max_chars]
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


def prepare_profile_for_llm(profile: Any) -> dict:
    """Return only the profile fields the LLM needs for scoring. Redacts PII.

    Security contract:
    - Uses an explicit allowlist (frozenset). Anything not listed is excluded.
    - Exact salary figure is NEVER included — replaced with a signal string.
    - Relocation preference is a job criterion (not personal data), included.
    - geo_cities are job targets, not current address — included.

    Args:
        profile: Profile dataclass instance (duck-typed; see capabilities/career_os/models.py).

    Returns:
        dict safe to serialize and pass to the LLM.
    """
    result: dict = {}

    for field in _PROFILE_ALLOWED_FIELDS:
        value = getattr(profile, field, None)
        if value is not None:
            result[field] = value

    # Salary: signal only — exact figure is redacted
    salary_min = getattr(profile, "salary_min", None)
    result["salary_signal"] = (
        "has_minimum_threshold" if salary_min else "no_minimum_specified"
    )

    return result
