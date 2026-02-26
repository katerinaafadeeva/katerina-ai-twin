"""Advanced HH vacancy prefilter from hh_filters.json.

Applies identity-level filters that go beyond profile-based negative_signals:
  - Salary floor (min_salary_rub) with allow_no_salary toggle
  - Keyword exclusions (exclude_keywords)
  - Required keywords — at least one must match (required_keywords_any)

Module-level cache: the JSON file is read once and cached per path.
Returns (True, "") if vacancy passes all filters,
        (False, reason) if rejected — reason is logged by the caller.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# {path: filters_dict} — loaded once, cached indefinitely (config-level file)
_filters_cache: Dict[str, Dict[str, Any]] = {}


def _load_filters(path: str) -> Dict[str, Any]:
    """Load hh_filters.json. Caches result per path (module-level).

    Returns empty dict if file not found or invalid — all filters pass by default.
    """
    if path in _filters_cache:
        return _filters_cache[path]

    p = Path(path)
    if not p.exists():
        logger.info(
            "hh_filters.json not found at %r — advanced prefilter disabled", path
        )
        _filters_cache[path] = {}
        return {}

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Failed to load hh_filters.json at %r: %s — skipping advanced filter",
            path,
            exc,
        )
        _filters_cache[path] = {}
        return {}

    if not isinstance(data, dict):
        logger.warning(
            "hh_filters.json must be a JSON object, got %s — skipping",
            type(data).__name__,
        )
        _filters_cache[path] = {}
        return {}

    _filters_cache[path] = data
    logger.info("hh_filters.json loaded from %r", path)
    return data


def should_score_advanced(
    vacancy_text: str,
    salary_min: Optional[int],
    salary_currency: str,
    has_salary: bool,
    filters_path: str,
) -> Tuple[bool, str]:
    """Check if vacancy passes advanced identity-level filters from hh_filters.json.

    Checks (in order):
    1. Salary floor (min_salary_rub, only for RUR):
       - has_salary + RUR + salary_min below floor → reject
       - no salary + allow_no_salary=false → reject
    2. exclude_keywords: any match in vacancy_text → reject
    3. required_keywords_any: if list non-empty, at least one must match → reject if none

    Non-RUR salaries and vacancies with salary.to only (salary_min=None) are
    not filtered by the salary floor — conservative pass-through.

    Args:
        vacancy_text: Full vacancy text for keyword matching.
        salary_min: Value of salary.from from HH API, or None.
        salary_currency: Currency code from HH API ("RUR", "USD", etc.).
        has_salary: True if HH API returned a salary object for this vacancy.
        filters_path: Path to hh_filters.json.

    Returns:
        (True, "") if vacancy passes all filters.
        (False, reason) if rejected.
    """
    filters = _load_filters(filters_path)
    if not filters:
        return True, ""

    text_lower = vacancy_text.lower()

    # 1. Salary floor (RUR only)
    min_salary_rub: Optional[int] = filters.get("min_salary_rub")
    allow_no_salary: bool = filters.get("allow_no_salary", True)

    if min_salary_rub is not None:
        if has_salary and salary_currency == "RUR":
            if salary_min is not None and salary_min < min_salary_rub:
                return False, f"salary_below_floor: {salary_min} < {min_salary_rub} RUB"
        elif not has_salary and not allow_no_salary:
            return False, "no_salary_not_allowed"

    # 2. Exclude keywords
    for keyword in filters.get("exclude_keywords", []):
        if keyword.lower() in text_lower:
            return False, f"exclude_keyword: {keyword}"

    # 3. Required keywords — at least one must match
    required_any = filters.get("required_keywords_any", [])
    if required_any:
        if not any(kw.lower() in text_lower for kw in required_any):
            return False, "required_keywords_any: no match"

    return True, ""
