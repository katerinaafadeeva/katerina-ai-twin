"""Telegram handlers for control_plane skill.

Approval callbacks (inline buttons) and operator commands:
  /today — daily summary
  /limits — policy thresholds and remaining capacity
  /stats — /today + list of pending APPROVAL_REQUIRED actions

All handlers check authorization. All DB queries are deterministic SQL (no LLM).
"""

import logging
from datetime import date
from typing import Optional, Tuple

from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core.config import config
from core.db import get_conn
from core.events import emit
from core.security import is_authorized
from capabilities.career_os.skills.control_plane.store import (
    get_action_by_id,
    get_pending_approvals,
    get_policy_display,
    get_today_summary,
    update_action_status,
)

logger = logging.getLogger(__name__)

# Mapping from callback action string → DB status
_ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "snooze": "snoozed",
}

# Mapping from new_status → user-facing answer text
_STATUS_ANSWER = {
    "approved": "✅ Одобрено",
    "rejected": "❌ Отклонено",
    "snoozed": "⏸ Отложено",
}

# Mapping from new_status → suffix appended to the original message
_STATUS_SUFFIX = {
    "approved": "\n\n✅ Одобрено оператором",
    "rejected": "\n\n❌ Отклонено оператором",
    "snoozed": "\n\n⏸ Отложено",
}

# Mapping from new_status → event name emitted
_STATUS_EVENT = {
    "approved": "vacancy.approved",
    "rejected": "vacancy.rejected",
    "snoozed": "vacancy.snoozed",
}


def is_callback_authorized(callback: CallbackQuery) -> bool:
    """Check if the callback sender is in the allowed list.

    In dev mode (empty ALLOWED_TELEGRAM_IDS), all users are allowed.
    """
    if not config.allowed_telegram_ids:
        logger.warning("ALLOWED_TELEGRAM_IDS is empty — dev mode, all users allowed")
        return True
    return callback.from_user is not None and callback.from_user.id in config.allowed_telegram_ids


def _parse_callback(data: str) -> Optional[Tuple[str, int]]:
    """Parse callback_data in format '{action}:{action_id}'.

    Returns:
        (action_str, action_id) tuple, or None if format is invalid.
    """
    try:
        action, id_str = data.split(":", 1)
        if action not in _ACTION_TO_STATUS:
            return None
        action_id = int(id_str)
        return action, action_id
    except (ValueError, AttributeError):
        return None


async def handle_approval_callback(callback: CallbackQuery) -> None:
    """Handle approve/reject/snooze inline button callbacks.

    Flow:
    1. Authorize sender.
    2. Parse callback_data → (action, action_id).
    3. Load action from DB; validate action_type == APPROVAL_REQUIRED.
    4. Transition status via update_action_status (idempotent guard).
    5. Emit vacancy event.
    6. Edit original message (append decision, remove keyboard).
    7. Always call callback.answer() to stop button spinner.
    """
    # 1. Authorization
    if not is_callback_authorized(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # 2. Parse callback_data
    parsed = _parse_callback(callback.data or "")
    if parsed is None:
        await callback.answer("Неверный формат", show_alert=True)
        return
    action, action_id = parsed

    # 3. Load action from DB
    with get_conn() as conn:
        action_row = get_action_by_id(conn, action_id)

        if action_row is None:
            await callback.answer("Действие не найдено", show_alert=True)
            return

        # 4. Validate action_type
        if action_row["action_type"] != "APPROVAL_REQUIRED":
            await callback.answer("Это действие не требует одобрения", show_alert=True)
            return

        # 5. Transition status
        new_status = _ACTION_TO_STATUS[action]
        updated = update_action_status(conn, action_id, new_status, actor="operator")

        if not updated:
            await callback.answer("Уже обработано", show_alert=True)
            return

        conn.commit()

    # 6. Emit event
    job_raw_id = action_row["job_raw_id"]
    score = action_row["score"]
    emit(
        _STATUS_EVENT[new_status],
        {"action_id": action_id, "job_raw_id": job_raw_id, "score": score},
        actor="operator",
    )

    # 7. Edit message, remove keyboard, then answer callback (stops button spinner last)
    # Order: update_status → emit → edit_text → edit_reply_markup → callback.answer()
    # Rationale: status is persisted before any Telegram I/O. If Telegram fails,
    # the DB state is already correct and the button will show "Уже обработано" on retry.
    if callback.message is not None:
        original_text = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(
            original_text + _STATUS_SUFFIX[new_status]
        )
        await callback.message.edit_reply_markup(reply_markup=None)

    answer_text = _STATUS_ANSWER[new_status]
    await callback.answer(answer_text)


async def cmd_today(message: Message) -> None:
    """/today — daily summary of ingested, scored, actions by type/status, limit usage."""
    if not is_authorized(message):
        return

    with get_conn() as conn:
        s = get_today_summary(conn, apply_daily_cap=config.apply_daily_cap)

    today_str = date.today().strftime("%d.%m.%Y")
    at = s["by_action_type"]
    st = s["by_status"]

    text = (
        f"📊 Сегодня ({today_str}):\n\n"
        f"Входящие: {s['total_ingested']}\n"
        f"Оценено: {s['total_scored']}\n\n"
        f"По решениям:\n"
        f"  🔴 Игнор: {at['IGNORE']}\n"
        f"  🟡 Авто-очередь: {at['AUTO_QUEUE']}\n"
        f"  🟡 Авто-отклик: {at['AUTO_APPLY']}\n"
        f"  ⏸ Холд: {at['HOLD']}\n"
        f"  🟢 На одобрение: {at['APPROVAL_REQUIRED']}\n\n"
        f"Статусы:\n"
        f"  ⏳ Ожидают: {st['pending']}\n"
        f"  ✅ Одобрено: {st['approved']}\n"
        f"  ❌ Отклонено: {st['rejected']}\n"
        f"  ⏸ Отложено: {st['snoozed']}\n\n"
        f"Лимит решений: {s['auto_count']}/{s['daily_limit']} (осталось {s['remaining']})\n"
        f"Отклики HH: {s['applies_done']}/{s['apply_daily_cap']}"
    )
    await message.answer(text)


async def cmd_limits(message: Message) -> None:
    """/limits — policy thresholds and remaining daily capacity."""
    if not is_authorized(message):
        return

    with get_conn() as conn:
        p = get_policy_display(conn)

    tl = p["threshold_low"]
    th = p["threshold_high"]

    text = (
        f"⚙️ Текущие пороги:\n\n"
        f"Порог игнора: <{tl} (оценка 0-{tl - 1} → игнор)\n"
        f"Порог одобрения: ≥{th} (оценка {th}-10 → одобрение)\n"
        f"Авто-диапазон: {tl}-{th - 1}\n\n"
        f"Дневной лимит: {p['daily_limit']}\n"
        f"Использовано сегодня: {p['today_auto_count']}\n"
        f"Осталось: {p['remaining']}"
    )
    await message.answer(text)


async def cmd_stats(message: Message) -> None:
    """/stats — /today summary + list of pending APPROVAL_REQUIRED actions."""
    if not is_authorized(message):
        return

    with get_conn() as conn:
        s = get_today_summary(conn, apply_daily_cap=config.apply_daily_cap)
        pending = get_pending_approvals(conn)

    # Build /today portion
    today_str = date.today().strftime("%d.%m.%Y")
    at = s["by_action_type"]
    st = s["by_status"]

    text = (
        f"📊 Сегодня ({today_str}):\n\n"
        f"Входящие: {s['total_ingested']}\n"
        f"Оценено: {s['total_scored']}\n\n"
        f"По решениям:\n"
        f"  🔴 Игнор: {at['IGNORE']}\n"
        f"  🟡 Авто-очередь: {at['AUTO_QUEUE']}\n"
        f"  🟡 Авто-отклик: {at['AUTO_APPLY']}\n"
        f"  ⏸ Холд: {at['HOLD']}\n"
        f"  🟢 На одобрение: {at['APPROVAL_REQUIRED']}\n\n"
        f"Статусы:\n"
        f"  ⏳ Ожидают: {st['pending']}\n"
        f"  ✅ Одобрено: {st['approved']}\n"
        f"  ❌ Отклонено: {st['rejected']}\n"
        f"  ⏸ Отложено: {st['snoozed']}\n\n"
        f"Лимит решений: {s['auto_count']}/{s['daily_limit']} (осталось {s['remaining']})\n"
        f"Отклики HH: {s['applies_done']}/{s['apply_daily_cap']}\n\n"
    )

    # Pending approvals section
    text += "📋 Ожидают одобрения:\n\n"
    if not pending:
        text += "Нет вакансий на одобрении"
    else:
        from capabilities.career_os.skills.control_plane.formatters import extract_vacancy_title
        parts = []
        for row in pending:
            title, company = extract_vacancy_title(row.get("raw_text") or "")
            hh_id = row.get("hh_vacancy_id")
            hh_url = f"https://hh.ru/vacancy/{hh_id}" if hh_id else None
            card = (
                f"#{row['id']} | {title}"
                + (f" — {company}" if company else "")
                + f" | {row['score']}/10\n"
                + f"  {row['reason']}"
                + (f"\n  🔗 {hh_url}" if hh_url else "")
            )
            parts.append(card)
        text += "\n\n".join(parts)

    await message.answer(text)
