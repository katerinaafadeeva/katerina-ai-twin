"""HH.ru employer questionnaire auto-fill (popup path).

When an employer adds mandatory questions to the apply popup, this module
tries to answer them automatically before submitting the application.

Supported question types (rule-based, no LLM):
  - Salary / income          → profile salary range + negotiable phrasing
  - City / location          → profile location_base
  - Years of experience      → derived from profile
  - Start date / availability → fixed "2 weeks after offer" phrasing
  - Motivation / free-text   → skipped (returns unfilled → MANUAL_REQUIRED)

Unknown or unanswerable questions (dropdowns without safe defaults, radio
buttons, checkboxes, free-form motivation) are left unfilled and the caller
gets a list of skipped labels — it can then decide to proceed anyway (all
required fields filled) or fall back to MANUAL_REQUIRED.
"""

import logging
from typing import List, Optional, Tuple

from connectors.hh_browser import selectors

logger = logging.getLogger(__name__)

# Keywords identifying salary / income questions (Russian + English)
_SALARY_KEYWORDS = (
    "зарплат",
    "доход",
    "оклад",
    "вознаграждение",
    "ожидания по з",   # "ожидания по зарплате"
    "желаемый уровень",
    "ожидаемая",
    "уровень дохода",
    "salary",
    "compensation",
    "income",
    "expected pay",
)

# Keywords identifying location / city questions
_LOCATION_KEYWORDS = (
    "город",
    "регион",
    "местонахождени",
    "где вы",
    "location",
    "city",
    "where are you",
)

# Keywords identifying experience questions
_EXPERIENCE_KEYWORDS = (
    "опыт работы",
    "стаж",
    "лет работы",
    "сколько лет",
    "years of experience",
    "how many years",
)

# Keywords identifying start-date / availability questions
_START_DATE_KEYWORDS = (
    "когда",
    "готов",
    "можете приступить",
    "дата выхода",
    "start date",
    "available",
    "notice period",
)


def _match_keywords(text: str, keywords: tuple) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _build_salary_answer(profile) -> str:
    """Build a salary answer string from the profile.

    Uses profile.must_have.salary_min_rub as the floor.
    Range = [floor * 1.2, floor * 1.7] rounded to nearest 10k.
    If not available, falls back to a generic phrasing.
    """
    try:
        floor = 0
        must_have = getattr(profile, "must_have", None) or {}
        if isinstance(must_have, dict):
            floor = int(must_have.get("salary_min_rub", 0))
        if floor <= 0:
            # Try direct attribute (dataclass-style profile)
            floor = int(getattr(profile, "salary_min_rub", 0))
    except Exception:
        floor = 0

    if floor > 0:
        low = round(floor * 1.2 / 10_000) * 10
        high = round(floor * 1.7 / 10_000) * 10
        return (
            f"{low} 000 – {high} 000 руб. на руки, "
            "готова обсуждать в зависимости от задач и перспектив роста"
        )

    # Generic fallback (profile has no salary floor)
    return (
        "180 000 – 250 000 руб. на руки, "
        "готова обсуждать в зависимости от задач и перспектив роста"
    )


def _build_location_answer(profile) -> str:
    loc = getattr(profile, "location_base", "") or "Москва"
    return loc


def _build_experience_answer(_profile) -> str:
    return "5+ лет"


def _build_start_date_answer(_profile) -> str:
    return "В течение 2 недель после получения оффера"


async def _read_question_label(block) -> str:
    """Extract visible text from a question block label element."""
    # Try specific label selectors first
    for sel in (
        "label",
        "[class*='question-title']",
        "[class*='label']",
        "legend",
        "p",
        "span",
    ):
        try:
            el = await block.query_selector(sel)
            if el and await el.is_visible():
                text = (await el.inner_text()).strip()
                if text:
                    return text[:200]
        except Exception:
            continue
    # Fallback: full block text (first 200 chars)
    try:
        return (await block.inner_text()).strip()[:200]
    except Exception:
        return ""


async def _find_fillable_input(block):
    """Find the first visible fillable input within a question block.

    Returns (element, input_type) or (None, None).
    input_type is one of: 'text', 'textarea', 'select'
    """
    # Text / number inputs
    try:
        el = await block.query_selector(selectors.QUESTION_INPUT)
        if el and await el.is_visible():
            return el, "text"
    except Exception:
        pass
    # Textarea
    try:
        el = await block.query_selector(selectors.QUESTION_TEXTAREA)
        if el and await el.is_visible():
            return el, "textarea"
    except Exception:
        pass
    # Select (dropdown)
    try:
        el = await block.query_selector(selectors.QUESTION_SELECT)
        if el and await el.is_visible():
            return el, "select"
    except Exception:
        pass
    return None, None


async def fill_popup_questionnaire(
    page,
    profile,
    vacancy_url: str,
) -> Tuple[bool, List[str], List[str]]:
    """Try to fill all employer questions in the apply popup.

    Args:
        page:         Playwright Page (popup already open).
        profile:      Candidate Profile instance with must_have.salary_min_rub, etc.
        vacancy_url:  Vacancy URL (for logging).

    Returns:
        (all_filled: bool, filled_labels: list, skipped_labels: list)
        all_filled=True when every visible question block was successfully answered.
        filled_labels: question labels we answered.
        skipped_labels: question labels we could not answer (caller decides fate).
    """
    filled_labels: List[str] = []
    skipped_labels: List[str] = []

    try:
        question_blocks = await page.query_selector_all(selectors.POPUP_QUESTION)
    except Exception as exc:
        logger.warning("questionnaire: query_selector_all failed on %s: %s", vacancy_url, exc)
        return False, [], []

    if not question_blocks:
        return True, [], []

    for block in question_blocks:
        try:
            if not await block.is_visible():
                continue

            label = await _read_question_label(block)
            input_el, input_type = await _find_fillable_input(block)

            if input_el is None:
                # No fillable input found — skip silently (may be a container div)
                logger.debug("questionnaire: no input in block %r on %s", label[:60], vacancy_url)
                continue

            # Determine answer based on question type
            answer: Optional[str] = None

            if _match_keywords(label, _SALARY_KEYWORDS):
                answer = _build_salary_answer(profile)
            elif _match_keywords(label, _LOCATION_KEYWORDS):
                answer = _build_location_answer(profile)
            elif _match_keywords(label, _EXPERIENCE_KEYWORDS):
                answer = _build_experience_answer(profile)
            elif _match_keywords(label, _START_DATE_KEYWORDS):
                answer = _build_start_date_answer(profile)
            else:
                # Unknown question type — cannot answer safely
                logger.info(
                    "questionnaire: unknown question %r on %s — skipping",
                    label[:60], vacancy_url,
                )
                skipped_labels.append(label[:60])
                continue

            if input_type == "select":
                # Dropdown — skip (risky to guess the right option)
                logger.info(
                    "questionnaire: select dropdown %r on %s — skipping",
                    label[:60], vacancy_url,
                )
                skipped_labels.append(label[:60])
                continue

            await input_el.fill(answer)
            value = await input_el.input_value()
            if value:
                filled_labels.append(label[:60])
                logger.info(
                    "questionnaire: filled %r → %r on %s",
                    label[:60], answer[:60], vacancy_url,
                )
            else:
                logger.warning(
                    "questionnaire: fill appeared to fail for %r on %s",
                    label[:60], vacancy_url,
                )
                skipped_labels.append(label[:60])

        except Exception as exc:
            logger.warning(
                "questionnaire: error processing block on %s: %s", vacancy_url, exc
            )
            skipped_labels.append("unknown_block")

    all_filled = len(skipped_labels) == 0
    logger.info(
        "questionnaire: done on %s — filled=%d skipped=%d",
        vacancy_url, len(filled_labels), len(skipped_labels),
    )
    return all_filled, filled_labels, skipped_labels
