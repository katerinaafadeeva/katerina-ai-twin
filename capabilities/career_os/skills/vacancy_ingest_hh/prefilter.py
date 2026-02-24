"""Deterministic pre-filter for HH vacancies.

Rejects obvious mismatches before LLM scoring to save tokens.
No LLM calls. Uses profile.negative_signals and industries_excluded.
All matching is case-insensitive.
"""

import logging
from typing import Tuple

from capabilities.career_os.models import Profile

logger = logging.getLogger(__name__)


def should_score(vacancy_text: str, profile: Profile) -> Tuple[bool, str]:
    """Check if vacancy should be sent to LLM scoring.

    Args:
        vacancy_text: Raw vacancy text (name + snippet).
        profile: Loaded operator profile with filter lists.

    Returns:
        (True, "") if vacancy passes all filters.
        (False, reason) if vacancy is rejected — reason explains why.
    """
    text_lower = vacancy_text.lower()

    for signal in profile.negative_signals:
        if signal.lower() in text_lower:
            logger.debug("Pre-filter reject: negative_signal '%s'", signal)
            return False, f"negative_signal: {signal}"

    for industry in profile.industries_excluded:
        if industry.lower() in text_lower:
            logger.debug("Pre-filter reject: excluded_industry '%s'", industry)
            return False, f"excluded_industry: {industry}"

    return True, ""
