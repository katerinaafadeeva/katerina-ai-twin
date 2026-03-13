"""Telegram notification helpers for hh_apply outcomes.

All functions accept a Bot instance and a chat_id.
Each function corresponds to one apply outcome.
No LLM calls — pure message formatting.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# letter_status values that indicate the letter was successfully sent
_LETTER_SENT = {"sent_popup", "sent_inline", "sent_post_apply"}
_LETTER_SENT_CHAT = "sent_chat"
_LETTER_NOT_SENT = {"no_field_found", "chat_closed", "fill_failed"}


async def notify_apply_done(
    bot,
    chat_id: int,
    job_raw_id: int,
    apply_url: str,
    letter_status: Optional[str] = None,
    action_id: Optional[int] = None,
    cover_letter_text: Optional[str] = None,
    score: Optional[int] = None,
    vacancy_title: Optional[str] = None,
) -> None:
    """Notify operator that an application was submitted.

    Message text depends on whether a cover letter was attached:
      sent_popup/inline/post_apply → ✅ Отклик + 📝 письмо
      sent_chat                    → ✅ Отклик + 💬 письмо в чате
      no_field_found/closed/failed → ⚠️ Отклик без письма (reason)
      not_requested / None         → ✅ Отклик отправлен

    When cover_letter_text is provided the full letter text is appended
    (truncated to stay within Telegram's 4096-char limit).
    score and vacancy_title are shown in the header line when provided.
    """
    try:
        tag = f" [action={action_id}]" if action_id is not None else ""
        score_line = f" | Score: {score}/10" if score is not None else ""
        title_line = f"{vacancy_title}\n" if vacancy_title else ""

        if letter_status in _LETTER_SENT:
            header = f"✅ Отклик + 📝 письмо{score_line}: #{job_raw_id}{tag}"
        elif letter_status == _LETTER_SENT_CHAT:
            header = f"✅ Отклик + 💬 письмо в чате{score_line}: #{job_raw_id}{tag}"
        elif letter_status in _LETTER_NOT_SENT:
            header = f"⚠️ Отклик без письма ({letter_status}){score_line}: #{job_raw_id}{tag}"
        else:
            # not_requested or legacy None
            header = f"✅ Отклик отправлен{score_line}: #{job_raw_id}{tag}"

        text = f"{header}\n{title_line}{apply_url}"

        if cover_letter_text:
            cl_header = "\n\n📝 Сопроводительное:\n"
            max_letter = 4096 - len(text) - len(cl_header) - 10
            if max_letter > 50:
                body = cover_letter_text[:max_letter]
                if len(cover_letter_text) > max_letter:
                    body += "…"
                text += f"{cl_header}{body}"

        await bot.send_message(chat_id, text)
    except Exception:
        logger.exception("Failed to send apply_done notification for job %d", job_raw_id)


async def notify_manual_required(
    bot,
    chat_id: int,
    job_raw_id: int,
    apply_url: str,
    action_id: Optional[int] = None,
    score: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    """Notify operator that manual action is required (apply button not found)."""
    try:
        tag = f" [action={action_id}]" if action_id is not None else ""
        score_line = f"\nScore: {score}" if score is not None else ""
        reason_line = f"\nПричина: {reason}" if reason else ""
        await bot.send_message(
            chat_id,
            f"⚠️ Требуется ручное действие: вакансия #{job_raw_id}{tag}{score_line}{reason_line}\n"
            f"Откликнитесь вручную:\n{apply_url}",
        )
    except Exception:
        logger.exception("Failed to send manual_required notification for job %d", job_raw_id)


async def notify_captcha(
    bot,
    chat_id: int,
) -> None:
    """Notify operator that a captcha was detected — batch stopped."""
    try:
        await bot.send_message(
            chat_id,
            "🤖 Обнаружена капча на HH.ru — авто-отклики приостановлены.\n"
            "Зайдите на hh.ru вручную и решите капчу, затем бот продолжит работу.",
        )
    except Exception:
        logger.exception("Failed to send captcha notification")


async def notify_session_expired(
    bot,
    chat_id: int,
) -> None:
    """Notify operator that the HH.ru session has expired."""
    try:
        await bot.send_message(
            chat_id,
            "🔑 Сессия HH.ru истекла — авто-отклики остановлены.\n"
            "Отправьте /hh_login для инструкции по восстановлению.",
        )
    except Exception:
        logger.exception("Failed to send session_expired notification")


async def notify_batch_summary(
    bot,
    chat_id: int,
    done: int,
    skipped: int,
    failed: int,
    manual: int,
    results: Optional[list] = None,
) -> None:
    """Send a summary notification after a batch cycle completes.

    When results list is provided, each item should have:
    {"title": str, "url": str, "status": str, "error": Optional[str]}
    """
    if done == 0 and skipped == 0 and failed == 0 and manual == 0:
        return
    try:
        lines = [f"📋 Batch отклики: ✅{done} отправлено"]

        if results:
            done_items = [r for r in results if r.get("status") in ("done", "done_without_letter")]
            skipped_items = [r for r in results if r.get("status") == "already_applied"]
            manual_items = [r for r in results if r.get("status") == "manual_required"]
            failed_items = [r for r in results if r.get("status") in ("failed", "captcha", "session_expired")]

            for r in done_items:
                title = (r.get("title") or "?")[:60]
                url = r.get("url") or ""
                lines.append(f"  ✅ {title}" + (f" ({url})" if url else ""))

            if skipped_items:
                lines.append(f"  ⏩ {len(skipped_items)} уже откликались:")
                for r in skipped_items:
                    title = (r.get("title") or "?")[:60]
                    url = r.get("url") or ""
                    lines.append(f"    • {title}" + (f" ({url})" if url else ""))

            if manual_items:
                lines.append(f"  ⚠️ {len(manual_items)} требуют ручного действия:")
                for r in manual_items:
                    title = (r.get("title") or "?")[:60]
                    url = r.get("url") or ""
                    lines.append(f"    • {title}" + (f" ({url})" if url else ""))

            if failed_items:
                lines.append(f"  ❌ {len(failed_items)} ошибок:")
                for r in failed_items:
                    title = (r.get("title") or "?")[:60]
                    err = r.get("error") or ""
                    lines.append(f"    • {title}" + (f" — {err}" if err else ""))
        else:
            # Fallback: counts only (legacy callers)
            if skipped:
                lines.append(f"  ⏩ {skipped} уже откликались")
            if manual:
                lines.append(f"  ⚠️ {manual} требуют ручного действия")
            if failed:
                lines.append(f"  ❌ {failed} ошибок (повтор до 3 попыток)")

        # Truncate to Telegram limit
        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4093] + "…"
        await bot.send_message(chat_id, text)
    except Exception:
        logger.exception("Failed to send batch_summary notification")


async def notify_apply_cap_reached(
    bot,
    chat_id: int,
    cap: int,
) -> None:
    """Notify operator that the daily apply cap has been reached."""
    try:
        await bot.send_message(
            chat_id,
            f"🔒 Лимит откликов достигнут: {cap}/день.\n"
            f"Дальнейшие отклики будут отправлены завтра.",
        )
    except Exception:
        logger.exception("Failed to send apply_cap_reached notification")


async def notify_resume_apply(
    bot,
    chat_id: int,
    pending_count: int,
) -> None:
    """Acknowledge /resume_apply command."""
    try:
        if pending_count == 0:
            await bot.send_message(chat_id, "Нет вакансий в очереди на отклик.")
        else:
            await bot.send_message(
                chat_id,
                f"▶️ Возобновляю авто-отклики. В очереди: {pending_count} вакансий.",
            )
    except Exception:
        logger.exception("Failed to send resume_apply notification")
