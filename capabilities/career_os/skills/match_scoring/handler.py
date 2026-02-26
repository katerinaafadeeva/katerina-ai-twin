"""LLM scoring orchestration for match_scoring skill.

Pure async functions — no DB access. Connection lifecycle is owned by the
calling worker (worker.py).
"""

import json
import logging
import os
from typing import Optional, Tuple

from core.config import config
from core.llm.client import FALLBACK_MODEL, call_llm_scoring
from core.llm.prompts.scoring_v1 import PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE
from core.llm.sanitize import prepare_profile_for_llm, sanitize_for_llm
from core.llm.schemas import ScoringOutput
from capabilities.career_os.models import Profile

logger = logging.getLogger(__name__)

# Resume cache: (content, mtime_at_load). Re-read automatically if mtime changes.
# Empty string means "no resume" — scoring continues without resume context.
# Cache is invalidated on next call when the file's mtime changes (e.g. after edit).
# Restart is NOT required when resume.md changes.
_resume_cache: Tuple[str, Optional[float]] = ("", None)

_RESUME_MAX_CHARS = 20_000


def _load_resume() -> str:
    """Load resume from RESUME_PATH. Returns empty string on any failure.

    Uses mtime-based cache: if the file changes on disk the next scoring
    call will re-read it automatically without a bot restart.
    Returns empty string (not an error) when the file is absent — scoring
    continues without resume context and a warning is logged.
    """
    global _resume_cache
    path = config.resume_path
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        logger.warning(
            "Resume file not found at %r — scoring without resume context", path
        )
        _resume_cache = ("", None)
        return ""

    cached_text, cached_mtime = _resume_cache
    if cached_mtime == mtime:
        return cached_text

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception as exc:
        logger.warning(
            "Failed to read resume file %r: %s — scoring without resume context", path, exc
        )
        _resume_cache = ("", mtime)
        return ""

    text = text[:_RESUME_MAX_CHARS]
    _resume_cache = (text, mtime)
    logger.info("Resume loaded/refreshed from %r (%d chars)", path, len(text))
    return text


async def score_vacancy_llm(
    vacancy_text: str,
    vacancy_id: int,
    profile: Profile,
    correlation_id: str,
) -> ScoringOutput:
    """Score a vacancy against a profile and resume using the LLM.

    Pure async function — performs no DB reads or writes. All persistence
    is handled by the caller (worker.py).

    Flow:
    1. Sanitize vacancy text (strip injection vectors, truncate).
    2. Prepare profile dict (allowlist fields, redact PII / exact salary).
    3. Load resume via mtime-cached _load_resume() (graceful: empty if missing).
    4. Build user message from USER_TEMPLATE.
    5. Call LLM via call_llm_scoring() (default model = Claude Haiku).
    6. On failure, retry once with FALLBACK_MODEL (Claude Sonnet).
    7. Propagate exception if both attempts fail.

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
    resume_text = _load_resume() or "(резюме не предоставлено)"

    user_message = USER_TEMPLATE.format(
        profile_json=profile_json,
        resume_text=resume_text,
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
    except Exception:
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
