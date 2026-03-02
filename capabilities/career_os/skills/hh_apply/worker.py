"""Async background worker for hh_apply skill.

Polls for AUTO_APPLY actions with no successful apply_run yet, submits applications
via Playwright, persists results in apply_runs, emits events, sends TG notifications.

Design rules:
- Feature flag: exits immediately if HH_APPLY_ENABLED=false
- COVER_LETTER_MODE=always (default): a cover letter is generated JIT if none exists in DB
- COVER_LETTER_MODE=never: skips cover letter for all applies
- All browser operations in try/except — failure does NOT crash the bot
- Daily cap enforced before each cycle
- Random delay between applies (anti-ban)
- Batch size cap per cycle
- Captcha → stop entire batch immediately (human action required)
- Session expired → stop entire batch, notify operator
- Each attempt saved as a separate apply_run row (full history)
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import Bot

from capabilities.career_os.skills.hh_apply.store import (
    get_hh_vacancy_url,
    get_pending_apply_tasks,
    get_today_apply_count,
    save_apply_run,
    was_apply_cap_notification_sent_today,
)
from capabilities.career_os.skills.hh_apply.notifier import (
    notify_apply_cap_reached,
    notify_apply_done,
    notify_batch_summary,
    notify_captcha,
    notify_manual_required,
    notify_session_expired,
)
from capabilities.career_os.models import Profile
from capabilities.career_os.skills.cover_letter.generator import (
    generate_cover_letter,
    get_fallback_letter,
)
from capabilities.career_os.skills.cover_letter.store import (
    get_today_cover_letter_count,
    save_cover_letter,
)
from connectors.hh_browser.apply_flow import ApplyStatus, apply_to_vacancy
from connectors.hh_browser.client import HHBrowserClient
from core.config import config
from core.db import get_conn
from core.events import emit
from core.llm.prompts.cover_letter_v1 import PROMPT_VERSION as _CL_PROMPT_VERSION

logger = logging.getLogger(__name__)

# How often to run the apply cycle (seconds) — between batches
_CYCLE_INTERVAL = 300


def _now_utc() -> str:
    """Return current UTC datetime as ISO string for DB storage."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _ensure_cover_letter(
    action_id: int,
    job_raw_id: int,
    vacancy_text: str,
    correlation_id: str,
) -> str:
    """Return a cover letter string for the given action, generating JIT if needed.

    Logic:
    1. If vacancy_text is empty → can't generate; return "" and log warning.
    2. Check daily cap. If cap reached → use static fallback letter (still better than "").
    3. Otherwise generate via LLM, save to cover_letters, return the text.
    4. Any exception → log and return "" so the apply can still proceed.
    """
    if not vacancy_text:
        logger.warning(
            "jit_cover_letter: no vacancy_text action_id=%d job_raw_id=%d"
            " — applying without letter",
            action_id, job_raw_id,
        )
        return ""

    # Daily cap check
    cap = config.cover_letter_daily_cap
    if cap > 0:
        with get_conn() as conn:
            cl_count = get_today_cover_letter_count(conn)
        if cl_count >= cap:
            fallback = get_fallback_letter()
            logger.warning(
                "jit_cover_letter: daily cap reached (%d/%d) action_id=%d"
                " — using static fallback (len=%d)",
                cl_count, cap, action_id, len(fallback),
            )
            return fallback

    try:
        profile = Profile.from_file(config.profile_path)
        letter_text, is_fb, in_tok, out_tok, cost = await generate_cover_letter(
            vacancy_text=vacancy_text,
            vacancy_id=job_raw_id,
            profile=profile,
            score_reasons="",   # no scoring context in apply worker
            correlation_id=correlation_id,
        )
        with get_conn() as conn:
            save_cover_letter(
                conn,
                job_raw_id=job_raw_id,
                action_id=action_id,
                letter_text=letter_text,
                model="fallback" if is_fb else "claude-haiku-4-5-20251001",
                prompt_version=_CL_PROMPT_VERSION,
                is_fallback=is_fb,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
            )
            conn.commit()
        logger.info(
            "jit_cover_letter: generated action_id=%d job_raw_id=%d"
            " is_fallback=%s len=%d",
            action_id, job_raw_id, is_fb, len(letter_text),
        )
        return letter_text
    except Exception:
        logger.exception(
            "jit_cover_letter: generation failed action_id=%d — applying without letter",
            action_id,
        )
        return ""


async def hh_apply_worker(bot: Bot) -> None:
    """Background worker: picks pending AUTO_APPLY tasks and submits via browser.

    Exits immediately if HH_APPLY_ENABLED=false.
    Runs in a loop with _CYCLE_INTERVAL seconds sleep between cycles.

    Args:
        bot: aiogram Bot instance for Telegram notifications.
    """
    if not config.hh_apply_enabled:
        logger.info("HH Apply worker disabled (HH_APPLY_ENABLED=false) — exiting")
        return

    # Warn if storage state file is missing (worker continues — file may appear later)
    if not os.path.exists(config.hh_storage_state_path):
        logger.warning(
            "HH_APPLY_ENABLED=true but storage state not found at %s. "
            "Run: python -m connectors.hh_browser.bootstrap",
            config.hh_storage_state_path,
        )
        if config.allowed_telegram_ids:
            try:
                await bot.send_message(
                    config.allowed_telegram_ids[0],
                    "⚠️ Авто-отклики включены, но сессия HH.ru не найдена.\n"
                    "Отправьте /hh_login для инструкции.",
                )
            except Exception:
                pass

    logger.info(
        "HH Apply worker started — cap=%d delay=[%.1f..%.1f]s batch=%d",
        config.apply_daily_cap,
        config.apply_delay_min,
        config.apply_delay_max,
        config.apply_batch_size,
    )

    while True:
        try:
            await _run_apply_cycle(bot)
        except Exception:
            logger.exception("Apply worker cycle-level error")
        await asyncio.sleep(_CYCLE_INTERVAL)


async def _run_apply_cycle(bot: Bot) -> None:
    """Execute one apply cycle: pick tasks → browser → save apply_run → notify."""
    chat_id = config.allowed_telegram_ids[0] if config.allowed_telegram_ids else None

    # --- Daily cap check (before any browser work) ---
    if config.apply_daily_cap > 0:
        with get_conn() as conn:
            today_count = get_today_apply_count(conn)
        if today_count >= config.apply_daily_cap:
            logger.info(
                "Apply daily cap reached (%d/%d) — skipping cycle",
                today_count,
                config.apply_daily_cap,
            )
            # Emit-first durability (same pattern as scoring cap and HOLD summary)
            with get_conn() as conn:
                already_notified = was_apply_cap_notification_sent_today(conn)
            if not already_notified and chat_id:
                emit(
                    "apply.cap_reached",
                    {"cap": config.apply_daily_cap, "today": today_count},
                    actor="hh_apply_worker",
                )
                await notify_apply_cap_reached(bot, chat_id, config.apply_daily_cap)
            return

    # --- Pick pending tasks ---
    with get_conn() as conn:
        tasks = get_pending_apply_tasks(conn, limit=config.apply_batch_size)

    if not tasks:
        logger.debug("No pending apply tasks")
        return

    logger.info("Apply cycle: %d tasks to process", len(tasks))

    # --- Per-cycle counters for batch summary ---
    done_count = 0
    skipped_count = 0
    failed_count = 0
    manual_count = 0

    browser_client = HHBrowserClient()

    try:
        async with browser_client.session(config.hh_storage_state_path) as context:
            for task in tasks:
                action_id = task["action_id"]
                job_raw_id = task["job_raw_id"]
                hh_vacancy_id = task["hh_vacancy_id"]
                raw_letter = task.get("cover_letter")
                cover_letter = raw_letter or ""
                correlation_id = task.get("correlation_id") or str(uuid4())

                # --- JIT cover letter (COVER_LETTER_MODE=always, default) ---
                if not cover_letter and config.cover_letter_mode != "never":
                    cover_letter = await _ensure_cover_letter(
                        action_id=action_id,
                        job_raw_id=job_raw_id,
                        vacancy_text=task.get("vacancy_text") or "",
                        correlation_id=correlation_id,
                    )
                elif not cover_letter:
                    logger.info(
                        "cover_letter: skipped (COVER_LETTER_MODE=never)"
                        " action_id=%d job_raw_id=%d",
                        action_id, job_raw_id,
                    )
                # Next attempt number = existing runs + 1
                next_attempt = task["attempt_count"] + 1

                vacancy_url = get_hh_vacancy_url(hh_vacancy_id)
                finished_at = _now_utc()

                try:
                    page = await context.new_page()
                    try:
                        result = await apply_to_vacancy(page, vacancy_url, cover_letter)
                    finally:
                        await page.close()
                except Exception as exc:
                    logger.exception("Browser page failed for vacancy %d", job_raw_id)
                    with get_conn() as conn:
                        exc_rowid = save_apply_run(
                            conn,
                            action_id=action_id,
                            attempt=next_attempt,
                            status="failed",
                            error=str(exc)[:500],
                            apply_url=vacancy_url,
                            finished_at=finished_at,
                        )
                        conn.commit()
                    if not exc_rowid:
                        # INSERT OR IGNORE hit — concurrent cycle already saved this attempt.
                        logger.info(
                            "apply_run duplicate (concurrent cycle) action_id=%d attempt=%d"
                            " — skipping",
                            action_id, next_attempt,
                        )
                        continue
                    failed_count += 1
                    continue

                # --- Persist apply_run (one row per attempt) ---
                with get_conn() as conn:
                    run_rowid = save_apply_run(
                        conn,
                        action_id=action_id,
                        attempt=next_attempt,
                        status=result.status.value,
                        error=result.error or None,
                        apply_url=result.apply_url,
                        finished_at=finished_at,
                        flow_type=result.flow_type or None,
                        letter_status=result.letter_status or None,
                        letter_len=result.letter_len,
                        textarea_found=result.textarea_found,
                        detected_outcome=result.detected_outcome or None,
                        final_url=result.final_url or None,
                        chat_available=result.chat_available,
                    )
                    conn.commit()

                # INSERT OR IGNORE hit — concurrent cycle already saved this attempt.
                # Skip emit + notification to avoid duplicates.
                if not run_rowid:
                    logger.info(
                        "apply_run duplicate (concurrent cycle) action_id=%d attempt=%d"
                        " status=%s — skipping emit+notify",
                        action_id, next_attempt, result.status.value,
                    )
                    continue

                # --- Emit event ---
                event_name = f"apply.{result.status.value}"
                emit(
                    event_name,
                    {
                        "job_raw_id": job_raw_id,
                        "action_id": action_id,
                        "apply_url": result.apply_url,
                        "error": result.error or None,
                    },
                    actor="hh_apply_worker",
                    correlation_id=correlation_id,
                )

                # --- Telegram notifications per outcome ---
                if result.status in (ApplyStatus.DONE, ApplyStatus.DONE_WITHOUT_LETTER):
                    done_count += 1
                    if chat_id:
                        await notify_apply_done(
                            bot, chat_id, job_raw_id, result.apply_url,
                            letter_status=result.letter_status,
                            action_id=action_id,
                        )

                elif result.status == ApplyStatus.ALREADY_APPLIED:
                    skipped_count += 1
                    # silent — no per-vacancy notification

                elif result.status == ApplyStatus.MANUAL_REQUIRED:
                    manual_count += 1
                    if chat_id:
                        await notify_manual_required(
                            bot, chat_id, job_raw_id, result.apply_url,
                            action_id=action_id,
                        )

                elif result.status == ApplyStatus.CAPTCHA:
                    # Stop entire batch — captcha requires human action
                    logger.warning("Captcha detected — stopping apply batch")
                    if chat_id:
                        await notify_captcha(bot, chat_id)
                    break

                elif result.status == ApplyStatus.SESSION_EXPIRED:
                    # Stop entire batch — auth state expired
                    logger.warning("Session expired — stopping apply batch")
                    if chat_id:
                        await notify_session_expired(bot, chat_id)
                    break

                elif result.status == ApplyStatus.FAILED:
                    failed_count += 1
                    # Silent per-vacancy — will retry (up to MAX_ATTEMPTS)

                # --- Anti-ban random delay ---
                if tasks.index(task) < len(tasks) - 1:
                    delay = random.uniform(config.apply_delay_min, config.apply_delay_max)
                    logger.debug("Anti-ban delay: %.1f s", delay)
                    await asyncio.sleep(delay)

    except Exception:
        logger.exception("Browser session failed during apply cycle")

    # --- Batch summary (only if something happened) ---
    if chat_id and (done_count + skipped_count + failed_count + manual_count) > 0:
        await notify_batch_summary(
            bot,
            chat_id,
            done=done_count,
            skipped=skipped_count,
            failed=failed_count,
            manual=manual_count,
        )

    logger.info(
        "Apply cycle complete — done=%d skipped=%d failed=%d manual=%d",
        done_count,
        skipped_count,
        failed_count,
        manual_count,
    )
