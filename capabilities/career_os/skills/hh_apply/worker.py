"""Async background worker for hh_apply skill.

Polls for AUTO_APPLY actions with no successful apply_run yet, submits applications
via Playwright, persists results in apply_runs, emits events, sends TG notifications.

Design rules:
- Feature flag: exits immediately if HH_APPLY_ENABLED=false
- Zero LLM calls — pure browser automation
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
from connectors.hh_browser.apply_flow import ApplyStatus, apply_to_vacancy
from connectors.hh_browser.client import HHBrowserClient
from core.config import config
from core.db import get_conn
from core.events import emit

logger = logging.getLogger(__name__)

# How often to run the apply cycle (seconds) — between batches
_CYCLE_INTERVAL = 300


def _now_utc() -> str:
    """Return current UTC datetime as ISO string for DB storage."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
                cover_letter = task.get("cover_letter") or ""
                correlation_id = task.get("correlation_id") or str(uuid4())
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
                        save_apply_run(
                            conn,
                            action_id=action_id,
                            attempt=next_attempt,
                            status="failed",
                            error=str(exc)[:500],
                            apply_url=vacancy_url,
                            finished_at=finished_at,
                        )
                        conn.commit()
                    failed_count += 1
                    continue

                # --- Persist apply_run (one row per attempt) ---
                with get_conn() as conn:
                    save_apply_run(
                        conn,
                        action_id=action_id,
                        attempt=next_attempt,
                        status=result.status.value,
                        error=result.error or None,
                        apply_url=result.apply_url,
                        finished_at=finished_at,
                    )
                    conn.commit()

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
                        await notify_apply_done(bot, chat_id, job_raw_id, result.apply_url)

                elif result.status == ApplyStatus.ALREADY_APPLIED:
                    skipped_count += 1
                    # silent — no per-vacancy notification

                elif result.status == ApplyStatus.MANUAL_REQUIRED:
                    manual_count += 1
                    if chat_id:
                        await notify_manual_required(bot, chat_id, job_raw_id, result.apply_url)

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
