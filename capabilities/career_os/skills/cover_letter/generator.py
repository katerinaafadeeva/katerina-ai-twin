"""Cover letter generation — LLM call with fallback and length retry.

Pure async functions — no DB access. Connection lifecycle owned by caller.
On any LLM failure, returns the fallback template with is_fallback=True.

Length validator: if LLM returns > 550 characters, one retry is made with
a strict shorten instruction. The retry result is used regardless of length
(the LLM is expected to comply); fallback is used only on total LLM failure.
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
from core.llm.resume import get_resume_text
from core.llm.sanitize import prepare_profile_for_llm, sanitize_for_llm

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"

# Target length window (characters)
_LETTER_MIN_CHARS = 50
_LETTER_MAX_CHARS = 550  # above this → one retry to shorten

# Module-level cache so the file is read at most once per process
_fallback_cache: str = ""

_SHORTEN_SYSTEM = (
    "You are editing a cover letter. Shorten it to exactly 450–500 characters. "
    "Keep the structure and bullet points. Output the letter text ONLY."
)

# Negative / rejection phrases that must never appear in a cover letter.
# If any match, the letter is replaced with the static fallback.
_NEGATIVE_PATTERNS = (
    "не соответствует",
    "не подходит",
    "не подхожу",
    "не интересна",
    "не интересует",
    "не вижу себя",
    "не считаю себя",
    "к сожалению",
    "однако я должна сказать",
    "однако должна сказать",
    "эта позиция не",
    "данная позиция не",
    "вакансия не",
    "не вполне",
    "not a good fit",
    "not the right fit",
    "does not match",
    "do not match",
    "not aligned",
    "unfortunately",
)


def _has_negative_phrases(text: str) -> bool:
    """Return True if the letter contains any forbidden negative phrases."""
    lower = text.lower()
    return any(pattern in lower for pattern in _NEGATIVE_PATTERNS)


def _safe_load_resume() -> str:
    """Load resume via shared cache; swallow all exceptions (returns '' on failure)."""
    try:
        return get_resume_text(config.resume_path)
    except Exception:
        return ""


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
    resume_text: str = "",
) -> Tuple[str, bool, int, int, float]:
    """Generate a cover letter via LLM with length validation and one retry.

    Args:
        vacancy_text: Raw vacancy text (will be sanitized).
        vacancy_id:   job_raw.id for audit logging.
        profile:      Operator profile (will be PII-redacted).
        score_reasons: Formatted reasons string from scoring output.
        correlation_id: UUID linking all events for this vacancy cycle.
        resume_text:  Optional pre-loaded resume text. If empty, loaded
                      internally from config.resume_path via shared cache.

    Returns:
        Tuple of (letter_text, is_fallback, input_tokens, output_tokens, cost_usd).
        On any failure, returns (fallback_text, True, 0, 0, 0.0).
    """
    if not resume_text:
        resume_text = _safe_load_resume()

    clean_text = sanitize_for_llm(vacancy_text, max_chars=1500)
    profile_dict = prepare_profile_for_llm(profile)
    profile_json = json.dumps(profile_dict, ensure_ascii=False, indent=2)
    resume_display = resume_text or "(резюме не предоставлено)"

    user_message = USER_TEMPLATE.format(
        profile_json=profile_json,
        resume_text=resume_display,
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
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        letter_text = response.content[0].text.strip()

        if len(letter_text) < _LETTER_MIN_CHARS:
            logger.warning(
                "Cover letter response too short (%d chars) for vacancy %d — using fallback",
                len(letter_text), vacancy_id,
            )
            return get_fallback_letter(), True, input_tokens, output_tokens, 0.0

        # Negative phrase guardrail — letter must always be positive and enthusiastic.
        if _has_negative_phrases(letter_text):
            logger.warning(
                "Cover letter contains negative/rejection phrases for vacancy %d"
                " — using fallback. Snippet: %.80r",
                vacancy_id, letter_text[:80],
            )
            return get_fallback_letter(), True, input_tokens, output_tokens, 0.0

        # Length retry: if response is too long, ask LLM to shorten it (once)
        if len(letter_text) > _LETTER_MAX_CHARS:
            logger.info(
                "Cover letter too long (%d chars) for vacancy %d — retrying with shorten instruction",
                len(letter_text), vacancy_id,
            )
            try:
                shorten_response = await client.messages.create(
                    model=_MODEL,
                    max_tokens=600,
                    temperature=0.2,
                    system=_SHORTEN_SYSTEM,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Сократи до 450–500 символов, сохрани структуру:\n\n{letter_text}"
                            ),
                        }
                    ],
                )
                input_tokens += shorten_response.usage.input_tokens
                output_tokens += shorten_response.usage.output_tokens
                shortened = shorten_response.content[0].text.strip()
                if len(shortened) >= _LETTER_MIN_CHARS:
                    letter_text = shortened
            except Exception:
                logger.warning(
                    "Cover letter shorten retry failed for vacancy %d — using original",
                    vacancy_id,
                    exc_info=True,
                )

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
