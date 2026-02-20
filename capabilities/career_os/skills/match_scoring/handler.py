"""LLM scoring orchestration for match_scoring skill.

Pure async functions — no DB access. Connection lifecycle is owned by the
calling worker (worker.py).
"""

import json
import logging

from core.llm.client import FALLBACK_MODEL, call_llm_scoring
from core.llm.prompts.scoring_v1 import PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE
from core.llm.sanitize import prepare_profile_for_llm, sanitize_for_llm
from core.llm.schemas import ScoringOutput
from capabilities.career_os.models import Profile

logger = logging.getLogger(__name__)


async def score_vacancy_llm(
    vacancy_text: str,
    vacancy_id: int,
    profile: Profile,
    correlation_id: str,
) -> ScoringOutput:
    """Score a vacancy against a profile using the LLM.

    Pure async function — performs no DB reads or writes. All persistence
    is handled by the caller (worker.py).

    Flow:
    1. Sanitize vacancy text (strip injection vectors, truncate).
    2. Prepare profile dict (allowlist fields, redact PII / exact salary).
    3. Build user message from USER_TEMPLATE.
    4. Call LLM via call_llm_scoring() (default model = Claude Haiku).
    5. On failure, retry once with FALLBACK_MODEL (Claude Sonnet).
    6. Propagate exception if both attempts fail.

    Args:
        vacancy_text: Raw vacancy text as received from the Telegram message.
        vacancy_id: DB id from job_raw (used for audit logging).
        profile: Loaded Profile instance with targeting preferences.
        correlation_id: UUID string linking all events for this scoring attempt.

    Returns:
        Validated ScoringOutput with score, reasons, and explanation.

    Raises:
        Exception: If both primary and fallback LLM calls fail.
    """
    clean_text = sanitize_for_llm(vacancy_text)
    profile_dict = prepare_profile_for_llm(profile)
    profile_json = json.dumps(profile_dict, ensure_ascii=False, indent=2)

    user_message = USER_TEMPLATE.format(
        profile_json=profile_json,
        vacancy_text=clean_text,
    )

    try:
        return await call_llm_scoring(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
            prompt_version=PROMPT_VERSION,
            job_raw_id=vacancy_id,
            correlation_id=correlation_id,
        )
    except Exception as primary_exc:
        logger.warning(
            "Primary LLM call failed for vacancy %d — retrying with fallback model %r",
            vacancy_id,
            FALLBACK_MODEL,
            exc_info=True,
        )

    # Retry with fallback model — propagate if this also fails
    return await call_llm_scoring(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        prompt_version=PROMPT_VERSION,
        job_raw_id=vacancy_id,
        correlation_id=correlation_id,
        model=FALLBACK_MODEL,
    )
