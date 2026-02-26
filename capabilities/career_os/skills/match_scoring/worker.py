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
from capabilities.career_os.skills.control_plane.formatters import extract_vacancy_title
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
from capabilities.career_os.skills.cover_letter.generator import (
    generate_cover_letter,
    get_fallback_letter,
)
from capabilities.career_os.skills.cover_letter.store import (
    get_today_cover_letter_count,
    save_cover_letter,
    was_cover_letter_cap_notification_sent_today,
)
from capabilities.career_os.skills.vacancy_ingest_hh.store import (
    get_today_scored_count,
    was_scoring_cap_notification_sent_today,
)
from core.config import config
from core.db import get_conn
from core.events import emit
from core.llm.prompts.cover_letter_v1 import PROMPT_VERSION as CL_PROMPT_VERSION
from core.llm.prompts.scoring_v1 import PROMPT_VERSION
from core.llm.resume import get_resume_text

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

            cap_reached_this_cycle = False
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

                    # --- Scoring daily cap check (before LLM call) ---
                    if config.hh_scoring_daily_cap > 0:
                        with get_conn() as conn:
                            scored_today = get_today_scored_count(conn)
                        if scored_today >= config.hh_scoring_daily_cap:
                            logger.info(
                                "Scoring daily cap reached (%d/%d) — stopping scoring this cycle",
                                scored_today,
                                config.hh_scoring_daily_cap,
                            )
                            cap_reached_this_cycle = True
                            break

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

                    # --- Cover letter generation (AUTO_APPLY and APPROVAL_REQUIRED only) ---
                    cover_letter_text = None
                    if decision.action_type in (ActionType.AUTO_APPLY, ActionType.APPROVAL_REQUIRED):
                        try:
                            reasons_text = "\n".join(
                                f"- {r.criterion}: {'✓' if r.matched else '✗'} {r.note}"
                                for r in result.reasons
                            )

                            use_fallback = False
                            if config.cover_letter_daily_cap > 0:
                                with get_conn() as conn:
                                    cl_today = get_today_cover_letter_count(conn)
                                if cl_today >= config.cover_letter_daily_cap:
                                    logger.info(
                                        "Cover letter daily cap reached (%d/%d) — using fallback",
                                        cl_today, config.cover_letter_daily_cap,
                                    )
                                    use_fallback = True

                            if use_fallback:
                                letter_text = get_fallback_letter()
                                is_fb, in_tok, out_tok, cost = True, 0, 0, 0.0
                            else:
                                letter_text, is_fb, in_tok, out_tok, cost = await generate_cover_letter(
                                    vacancy_text=vacancy["raw_text"],
                                    vacancy_id=job_raw_id,
                                    profile=profile,
                                    score_reasons=reasons_text,
                                    correlation_id=correlation_id,
                                    resume_text=get_resume_text(config.resume_path),
                                )

                            with get_conn() as conn:
                                save_cover_letter(
                                    conn,
                                    job_raw_id=job_raw_id,
                                    action_id=action_rowid,
                                    letter_text=letter_text,
                                    model="fallback" if is_fb else "claude-haiku-4-5-20251001",
                                    prompt_version=CL_PROMPT_VERSION,
                                    is_fallback=is_fb,
                                    input_tokens=in_tok,
                                    output_tokens=out_tok,
                                    cost_usd=cost,
                                )
                                conn.commit()

                            cover_letter_text = letter_text

                        except Exception:
                            logger.exception(
                                "Cover letter generation failed for vacancy %d — continuing",
                                job_raw_id,
                            )

                    # --- Telegram notification (per action type) ---
                    if config.allowed_telegram_ids:
                        chat_id = config.allowed_telegram_ids[0]
                        emoji = _score_emoji(result.score)
                        raw_text = vacancy.get("raw_text") or ""
                        title, company = extract_vacancy_title(raw_text)
                        hh_vacancy_id = vacancy.get("hh_vacancy_id")
                        hh_url = (
                            f"https://hh.ru/vacancy/{hh_vacancy_id}"
                            if hh_vacancy_id
                            else None
                        )
                        title_line = title + (f" — {company}" if company else "")

                        if decision.action_type == ActionType.IGNORE:
                            pass  # silent — no notification

                        elif decision.action_type == ActionType.AUTO_APPLY:
                            hh_suffix = f"\n🔗 {hh_url}" if hh_url else ""
                            await bot.send_message(
                                chat_id,
                                f"{emoji} Автоотклик HH: {title_line}\n"
                                f"Score: {result.score}/10 | {decision.reason}"
                                f"{hh_suffix}",
                            )

                        elif decision.action_type == ActionType.AUTO_QUEUE:
                            await bot.send_message(
                                chat_id,
                                f"{emoji} В очередь: {title_line}\n"
                                f"Score: {result.score}/10 | {decision.reason}",
                            )

                        elif decision.action_type == ActionType.APPROVAL_REQUIRED:
                            cl_preview = ""
                            if cover_letter_text:
                                preview = cover_letter_text[:200]
                                if len(cover_letter_text) > 200:
                                    preview += "..."
                                cl_preview = f"\n\n📝 Сопроводительное:\n{preview}"

                            hh_suffix = f"\n🔗 {hh_url}" if hh_url else ""
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
                                f"{emoji} {title_line}\n"
                                f"Score: {result.score}/10 | {decision.reason}\n"
                                f"{result.explanation}"
                                f"{hh_suffix}"
                                f"{cl_preview}",
                                reply_markup=keyboard,
                            )

                        elif decision.action_type == ActionType.HOLD:
                            pass  # silent per-vacancy — one daily summary sent below

                except Exception:
                    logger.exception(
                        "Scoring/policy failed for vacancy",
                        extra={"job_raw_id": job_raw_id},
                    )

            # --- Scoring cap notification (once per UTC day) ---
            # Ordering: emit FIRST (dedup marker), then send_message (same durability pattern as HOLD).
            if cap_reached_this_cycle and config.allowed_telegram_ids:
                try:
                    with get_conn() as conn:
                        already_notified = was_scoring_cap_notification_sent_today(conn)
                    if not already_notified:
                        emit(
                            "scoring.cap_reached",
                            {"cap": config.hh_scoring_daily_cap},
                            actor="scoring_worker",
                        )
                        chat_id = config.allowed_telegram_ids[0]
                        await bot.send_message(
                            chat_id,
                            f"🔒 Лимит скоринга достигнут: {config.hh_scoring_daily_cap}/день. "
                            f"Необработанные вакансии будут оценены завтра.",
                        )
                except Exception:
                    logger.exception("Scoring cap notification failed")

            # --- Cover letter cap notification (once per UTC day) ---
            # emit FIRST (dedup marker), then send_message — same durability pattern as HOLD.
            if config.cover_letter_daily_cap > 0 and config.allowed_telegram_ids:
                try:
                    with get_conn() as conn:
                        cl_today = get_today_cover_letter_count(conn)
                        cl_already_notified = was_cover_letter_cap_notification_sent_today(conn)
                    if cl_today >= config.cover_letter_daily_cap and not cl_already_notified:
                        emit(
                            "cover_letter.cap_reached",
                            {"cap": config.cover_letter_daily_cap},
                            actor="cover_letter_generator",
                        )
                        chat_id = config.allowed_telegram_ids[0]
                        await bot.send_message(
                            chat_id,
                            f"📝 Лимит сопроводительных достигнут: {config.cover_letter_daily_cap}/день. "
                            f"Дальнейшие письма будут по шаблону.",
                        )
                except Exception:
                    logger.exception("Cover letter cap notification failed")

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
