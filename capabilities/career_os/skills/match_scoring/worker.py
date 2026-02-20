"""Async background worker for match_scoring skill.

Polls for unscored vacancies, scores them via LLM, persists results,
emits events, and sends Telegram notifications.
"""

import asyncio
import logging
from uuid import uuid4

from aiogram import Bot

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.match_scoring.handler import score_vacancy_llm
from capabilities.career_os.skills.match_scoring.store import (
    get_unscored_vacancies,
    save_score,
)
from core.config import config
from core.db import get_conn
from core.events import emit
from core.llm.prompts.scoring_v1 import PROMPT_VERSION

logger = logging.getLogger(__name__)


def _score_emoji(score: int) -> str:
    """Return a colour-coded emoji for the given score (0–10).

    Thresholds match ADR-001:
    - >= 7 → green (APPROVAL_REQUIRED)
    - >= 5 → yellow (AUTO_QUEUE)
    - < 5  → red (IGNORE)

    Args:
        score: Integer score in range 0–10.

    Returns:
        One of "🟢", "🟡", or "🔴".
    """
    if score >= 7:
        return "🟢"
    elif score >= 5:
        return "🟡"
    return "🔴"


async def scoring_worker(bot: Bot) -> None:
    """Background worker: polls for unscored vacancies and scores them via LLM.

    Runs in an infinite loop. On each iteration:
    1. Fetches all unscored vacancies from job_raw (LEFT JOIN job_scores).
    2. For each vacancy: scores via LLM, persists result, emits event,
       sends Telegram notification.
    3. Per-vacancy errors are caught and logged; the loop continues.
    4. Loop-level errors are caught and logged; the worker sleeps and retries.

    Tokens and cost are tracked via the ``llm.call`` event emitted inside
    call_llm_scoring(). The model field in job_scores records that the actual
    model is captured in the audit event (not duplicated here).

    Args:
        bot: aiogram Bot instance (shared with the Telegram handler).
    """
    profile = Profile.from_file(config.profile_path)
    interval = config.scoring_worker_interval
    logger.info("Scoring worker started", extra={"interval": interval})

    while True:
        try:
            with get_conn() as conn:
                unscored = get_unscored_vacancies(conn)

            for vacancy in unscored:
                correlation_id = str(uuid4())
                job_raw_id = vacancy["id"]
                try:
                    result = await score_vacancy_llm(
                        vacancy_text=vacancy["raw_text"],
                        vacancy_id=job_raw_id,
                        profile=profile,
                        correlation_id=correlation_id,
                    )

                    with get_conn() as conn:
                        save_score(
                            conn,
                            job_raw_id,
                            result,
                            profile_hash=profile.content_hash(),
                            # Actual model is logged in the llm.call audit event;
                            # this field records that the score came from the LLM path.
                            model="llm_call",
                            prompt_version=PROMPT_VERSION,
                            input_tokens=0,   # tracked in llm.call event
                            output_tokens=0,  # tracked in llm.call event
                            cost_usd=0.0,     # tracked in llm.call event
                        )
                        conn.commit()

                    emit(
                        "vacancy.scored",
                        {"job_raw_id": job_raw_id, "score": result.score},
                        actor="scoring_worker",
                        correlation_id=correlation_id,
                    )

                    if config.allowed_telegram_ids:
                        chat_id = config.allowed_telegram_ids[0]
                        emoji = _score_emoji(result.score)
                        await bot.send_message(
                            chat_id,
                            f"Оценка #{job_raw_id}: {emoji} {result.score}/10\n"
                            f"{result.explanation}",
                        )

                except Exception:
                    logger.exception(
                        "Scoring failed for vacancy",
                        extra={"job_raw_id": job_raw_id},
                    )

        except Exception:
            logger.exception("Worker loop error")

        await asyncio.sleep(interval)
