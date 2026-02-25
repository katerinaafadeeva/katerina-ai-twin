"""Cover letter generation — LLM call with fallback.

Pure async functions — no DB access. Connection lifecycle owned by caller.
On any LLM failure, returns the fallback template with is_fallback=True.
"""

import json
import logging
import time
from pathlib import Path
from typing import Tuple

import anthropic

from capabilities.career_os.models import Profile
from core.config import config
from core.events import emit
from core.llm.prompts.cover_letter_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
)
from core.llm.sanitize import prepare_profile_for_llm, sanitize_for_llm

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"

# Module-level cache so the file is read at most once per process
_fallback_cache: str = ""


def _load_fallback() -> str:
    """Load fallback cover letter template. Cached after first load."""
    global _fallback_cache
    if _fallback_cache:
        return _fallback_cache

    path = Path(config.cover_letter_fallback_path)

    # Try real file first, then .example.txt sibling
    if not path.exists():
        example = path.parent / (path.stem + ".example.txt")
        if example.exists():
            path = example
        else:
            logger.warning(
                "No fallback cover letter template found at %s — using hardcoded default",
                config.cover_letter_fallback_path,
            )
            _fallback_cache = (
                "Добрый день! Ваша вакансия мне интересна, и я считаю, что мой опыт "
                "хорошо подходит для этой роли. Буду рада обсудить подробности."
            )
            return _fallback_cache

    _fallback_cache = path.read_text(encoding="utf-8").strip()
    return _fallback_cache


def get_fallback_letter() -> str:
    """Return the static fallback cover letter text (cached)."""
    return _load_fallback()


async def generate_cover_letter(
    vacancy_text: str,
    vacancy_id: int,
    profile: Profile,
    score_reasons: str,
    correlation_id: str,
) -> Tuple[str, bool, int, int, float]:
    """Generate a cover letter via LLM.

    Args:
        vacancy_text: Raw vacancy text (will be sanitized).
        vacancy_id:   job_raw.id for audit logging.
        profile:      Operator profile (will be PII-redacted).
        score_reasons: Formatted reasons string from scoring output.
        correlation_id: UUID linking all events for this vacancy cycle.

    Returns:
        Tuple of (letter_text, is_fallback, input_tokens, output_tokens, cost_usd).
        On any failure, returns (fallback_text, True, 0, 0, 0.0).
    """
    clean_text = sanitize_for_llm(vacancy_text, max_chars=1500)
    profile_dict = prepare_profile_for_llm(profile)
    profile_json = json.dumps(profile_dict, ensure_ascii=False, indent=2)

    user_message = USER_TEMPLATE.format(
        profile_json=profile_json,
        vacancy_text=clean_text,
        reasons_text=score_reasons,
    )

    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
    start = time.monotonic()
    input_tokens = 0
    output_tokens = 0

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=600,
            temperature=0.3,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        letter_text = response.content[0].text.strip()

        if len(letter_text) < 50:
            logger.warning(
                "Cover letter response too short (%d chars) for vacancy %d — using fallback",
                len(letter_text), vacancy_id,
            )
            return get_fallback_letter(), True, input_tokens, output_tokens, 0.0

        duration_ms = int((time.monotonic() - start) * 1000)

        # Compute cost using MODEL_PRICING from client.py
        from core.llm.client import MODEL_PRICING
        pricing = MODEL_PRICING.get(_MODEL, {"input": 0.0, "output": 0.0})
        cost = round(
            (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000,
            6,
        )

        # Emit audit event — failure here must not surface to caller
        try:
            emit(
                "llm.call",
                {
                    "task": "cover_letter",
                    "model": _MODEL,
                    "prompt_version": PROMPT_VERSION,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost,
                    "duration_ms": duration_ms,
                    "success": True,
                    "job_raw_id": vacancy_id,
                },
                actor="cover_letter_generator",
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception("Failed to emit llm.call audit event for cover letter")

        return letter_text, False, input_tokens, output_tokens, cost

    except Exception:
        logger.warning(
            "Cover letter LLM call failed for vacancy %d — using fallback",
            vacancy_id,
            exc_info=True,
        )
        return get_fallback_letter(), True, 0, 0, 0.0
