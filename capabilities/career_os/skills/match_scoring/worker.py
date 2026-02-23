"""Async background worker for match_scoring skill.

Polls for unscored vacancies, scores them via LLM, persists results,
evaluates policy, records actions, emits events, and sends Telegram notifications.
"""

import asyncio
import logging
from uuid import uuid4

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.apply_policy.engine import ActionType, evaluate_policy
from capabilities.career_os.skills.apply_policy.store import (
    get_policy,
    get_today_auto_count,
    get_today_hold_count,
    save_action,
    was_hold_notification_sent_today,
)
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
    - >= 5 → yellow (AUTO_QUEUE/AUTO_APPLY)
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
    """Background worker: polls for unscored vacancies, scores them, and applies policy.

    Runs in an infinite loop. On each iteration:
    1. Fetches all unscored vacancies from job_raw (LEFT JOIN job_scores).
    2. For each vacancy: scores via LLM, persists result, emits vacancy.scored.
    3. Evaluates apply_policy: saves action, emits vacancy.policy_applied,
       sends notification based on action type (IGNORE/HOLD are silent per-vacancy).
    4. After processing all vacancies: sends one HOLD summary if any HOLDs exist today
       and the summary was not yet sent.
    5. Per-vacancy errors are caught and logged; the loop continues.
    6. Loop-level errors are caught and logged; the worker sleeps and retries.

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
                    if not vacancy["raw_text"]:
                        logger.warning(
                            "Skipping vacancy with empty raw_text",
                            extra={"job_raw_id": job_raw_id},
                        )
                        continue

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
                            model="llm_call",
                            prompt_version=PROMPT_VERSION,
                            input_tokens=0,
                            output_tokens=0,
                            cost_usd=0.0,
                        )
                        conn.commit()

                    emit(
                        "vacancy.scored",
                        {"job_raw_id": job_raw_id, "score": result.score},
                        actor="scoring_worker",
                        correlation_id=correlation_id,
                    )

                    # --- Policy evaluation ---
                    with get_conn() as conn:
                        policy = get_policy(conn)
                        today_auto_count = get_today_auto_count(conn)

                    decision = evaluate_policy(
                        score=result.score,
                        source=vacancy["source"] or "",
                        threshold_low=policy["threshold_low"],
                        threshold_high=policy["threshold_high"],
                        daily_limit=policy["daily_limit"],
                        today_auto_count=today_auto_count,
                    )

                    with get_conn() as conn:
                        action_rowid = save_action(
                            conn,
                            job_raw_id,
                            decision,
                            score=result.score,
                            correlation_id=correlation_id,
                        )
                        conn.commit()

                    emit(
                        "vacancy.policy_applied",
                        {
                            "job_raw_id": job_raw_id,
                            "action_type": decision.action_type.value,
                            "score": result.score,
                        },
                        actor="policy_engine",
                        correlation_id=correlation_id,
                    )

                    # --- Telegram notification (per action type) ---
                    if config.allowed_telegram_ids:
                        chat_id = config.allowed_telegram_ids[0]
                        emoji = _score_emoji(result.score)

                        if decision.action_type == ActionType.IGNORE:
                            pass  # silent — no notification

                        elif decision.action_type == ActionType.AUTO_APPLY:
                            await bot.send_message(
                                chat_id,
                                f"{emoji} Автоотклик HH #{job_raw_id}: {result.score}/10\n"
                                f"{decision.reason}",
                            )

                        elif decision.action_type == ActionType.AUTO_QUEUE:
                            await bot.send_message(
                                chat_id,
                                f"{emoji} В очередь #{job_raw_id}: {result.score}/10\n"
                                f"{decision.reason}",
                            )

                        elif decision.action_type == ActionType.APPROVAL_REQUIRED:
                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{action_rowid}"),
                                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{action_rowid}"),
                                ],
                                [
                                    InlineKeyboardButton(text="⏸ Отложить", callback_data=f"snooze:{action_rowid}"),
                                ],
                            ])
                            await bot.send_message(
                                chat_id,
                                f"{emoji} Требует одобрения #{job_raw_id}: {result.score}/10\n"
                                f"{decision.reason}\n"
                                f"{result.explanation}",
                                reply_markup=keyboard,
                            )

                        elif decision.action_type == ActionType.HOLD:
                            pass  # silent per-vacancy — one daily summary sent below

                except Exception:
                    logger.exception(
                        "Scoring/policy failed for vacancy",
                        extra={"job_raw_id": job_raw_id},
                    )

            # --- HOLD daily summary (once per UTC day) ---
            # Ordering: emit FIRST (persistence), then send_message.
            # Rationale: if send_message fails after emit, dedup marker is recorded →
            # next cycle skips (missed notification). If send_message succeeded first and
            # emit failed → dedup marker lost → duplicate notification next cycle.
            # For a personal system, missing one summary < sending duplicates every cycle.
            if config.allowed_telegram_ids:
                try:
                    with get_conn() as conn:
                        hold_count = get_today_hold_count(conn)
                        already_sent = was_hold_notification_sent_today(conn)

                    if hold_count > 0 and not already_sent:
                        emit(
                            "policy.hold_summary",
                            {"hold_count": hold_count},
                            actor="policy_engine",
                        )
                        chat_id = config.allowed_telegram_ids[0]
                        await bot.send_message(
                            chat_id,
                            f"⏸ Сегодня на удержании: {hold_count} вакансий — дневной лимит исчерпан.",
                        )
                except Exception:
                    logger.exception("HOLD summary notification failed")

        except Exception:
            logger.exception("Worker loop error")

        await asyncio.sleep(interval)
