# TASK: PR-5 — Telegram Approval UX + Operator Commands

You are the Implementation Agent (Tech Lead). Work in branch `pr-5`.
Model: Sonnet. All explanations and final report must be in Russian.

**Do NOT re-architect PR-3 or PR-4. Do NOT modify policy rules.**

## Context

PR-4 (policy engine) is complete: 95 tests pass.
The scoring worker already sends APPROVAL_REQUIRED notifications as plain text.
PR-5 closes the operator control loop: inline buttons + commands.

**Read these files first:**
- `DECISIONS.md` (all business rules)
- `capabilities/career_os/skills/apply_policy/engine.py` (ActionType enum)
- `capabilities/career_os/skills/apply_policy/store.py` (save_action, get_policy)
- `capabilities/career_os/skills/match_scoring/worker.py` (current notification code)
- `connectors/telegram_bot.py` (current bot setup)
- `core/security.py` (is_authorized pattern)

## Non-negotiable Business Rules

1. Only actions with `action_type = 'APPROVAL_REQUIRED'` and `status = 'pending'` can be approved/rejected/snoozed.
2. On Approve: `action.status = 'approved'`, `updated_at = now`, emit `vacancy.approved`.
3. On Reject: `action.status = 'rejected'`, `updated_at = now`, emit `vacancy.rejected`.
4. On Snooze: `action.status = 'snoozed'`, `updated_at = now`, emit `vacancy.snoozed`. No timer — MVP only marks the status.
5. Policy engine behavior MUST NOT change. PR-4 code is frozen.
6. All handlers and callbacks MUST check authorization (is_authorized or equivalent for CallbackQuery).

---

## Step 1: Migration — Add updated_at to actions

Create `core/migrations/005_actions_updated_at.sql`:

```sql
ALTER TABLE actions ADD COLUMN updated_at TIMESTAMP;
```

Verify: `python -c "from core.db import init_db; init_db(); print('Migration 005 OK')"`

Commit: `feat(core): migration 005 — add updated_at to actions table`

---

## Step 2: Control Plane store — action state transitions + queries

Create `capabilities/career_os/skills/control_plane/__init__.py` — empty.

Create `capabilities/career_os/skills/control_plane/store.py`:

Functions to implement:

### `get_action_by_id(conn, action_id: int) -> Optional[dict]`
- SELECT * FROM actions WHERE id = ?
- Returns dict or None

### `update_action_status(conn, action_id: int, new_status: str, actor: str = "operator") -> bool`
- Only transitions FROM 'pending' are allowed
- If current status != 'pending': return False (idempotent guard)
- UPDATE actions SET status = ?, updated_at = datetime('now'), actor = ? WHERE id = ? AND status = 'pending'
- Check rowcount: if 0 → return False (already transitioned); if 1 → return True
- Uses parameterized SQL only

### `get_today_summary(conn) -> dict`
For /today command. Returns:
```python
{
    "total_ingested": int,      # COUNT job_raw WHERE date(created_at) = date('now')
    "total_scored": int,        # COUNT job_scores WHERE date(scored_at) = date('now')
    "by_action_type": {         # COUNT actions grouped by action_type, today
        "IGNORE": int,
        "AUTO_QUEUE": int,
        "AUTO_APPLY": int,
        "HOLD": int,
        "APPROVAL_REQUIRED": int,
    },
    "by_status": {              # COUNT actions grouped by status, today
        "pending": int,
        "approved": int,
        "rejected": int,
        "snoozed": int,
    },
    "auto_count": int,          # reuse get_today_auto_count logic
    "daily_limit": int,         # from policy table
    "remaining": int,           # daily_limit - auto_count
}
```

### `get_pending_approvals(conn) -> List[dict]`
For /stats command. Returns list of actions WHERE action_type = 'APPROVAL_REQUIRED' AND status = 'pending', ordered by created_at DESC. Each dict includes: action id, job_raw_id, score, reason, created_at.

### `get_policy_display(conn) -> dict`
For /limits command. Returns: threshold_low, threshold_high, daily_limit, today_auto_count, remaining.

All functions accept sqlite3.Connection. No get_conn() inside. Deterministic DB queries only — no LLM.

Commit: `feat(control_plane): add store — action state transitions + today/stats/limits queries`

---

## Step 3: Control Plane handlers — callbacks + commands

Create `capabilities/career_os/skills/control_plane/handlers.py`:

### Authorization for CallbackQuery

aiogram's `CallbackQuery` has `.from_user` but NOT `.message.from_user` reliably. Create:

```python
def is_callback_authorized(callback: CallbackQuery) -> bool:
    """Check if callback sender is in allowed list."""
    if not config.allowed_telegram_ids:
        return True  # dev mode
    return callback.from_user is not None and callback.from_user.id in config.allowed_telegram_ids
```

### Callback handler: `handle_approval_callback(callback: CallbackQuery)`

1. Check authorization → if not authorized, `await callback.answer("Нет доступа", show_alert=True)` and return.
2. Parse callback_data: format is `{action}:{action_id}` where action ∈ {approve, reject, snooze}. If parse fails → answer "Неверный формат" and return.
3. Open DB connection.
4. Call `get_action_by_id(conn, action_id)`. If None → answer "Действие не найдено".
5. If action['action_type'] != 'APPROVAL_REQUIRED' → answer "Это действие не требует одобрения".
6. Map action string to status: approve→'approved', reject→'rejected', snooze→'snoozed'.
7. Call `update_action_status(conn, action_id, new_status, actor="operator")`.
8. If False (already transitioned) → answer "Уже обработано".
9. If True → commit, emit event (`vacancy.approved` / `vacancy.rejected` / `vacancy.snoozed`) with payload {action_id, job_raw_id, score}, actor="operator".
10. Answer callback and edit the original message text to include the decision:
    - Approve: `await callback.answer("✅ Одобрено")`; edit message: append "\n\n✅ Одобрено оператором"
    - Reject: `await callback.answer("❌ Отклонено")`; edit message: append "\n\n❌ Отклонено оператором"
    - Snooze: `await callback.answer("⏸ Отложено")`; edit message: append "\n\n⏸ Отложено"
11. Remove inline keyboard from the message after action (edit_reply_markup with empty markup).

**CRITICAL: Always call `callback.answer()` to prevent button spinning.**

### Command handler: `/today`

```
📊 Сегодня ({date}):

Входящие: {total_ingested}
Оценено: {total_scored}

По решениям:
  🔴 Игнор: {IGNORE}
  🟡 Авто-очередь: {AUTO_QUEUE}
  🟡 Авто-отклик: {AUTO_APPLY}
  ⏸ Холд: {HOLD}
  🟢 На одобрение: {APPROVAL_REQUIRED}

Статусы:
  ⏳ Ожидают: {pending}
  ✅ Одобрено: {approved}
  ❌ Отклонено: {rejected}
  ⏸ Отложено: {snoozed}

Лимит: {auto_count}/{daily_limit} (осталось {remaining})
```

### Command handler: `/limits`

```
⚙️ Текущие пороги:

Порог игнора: <{threshold_low} (оценка 0-{threshold_low-1} → игнор)
Порог одобрения: ≥{threshold_high} (оценка {threshold_high}-10 → одобрение)
Авто-диапазон: {threshold_low}-{threshold_high-1}

Дневной лимит: {daily_limit}
Использовано сегодня: {auto_count}
Осталось: {remaining}
```

### Command handler: `/stats`

Same as /today, PLUS at the bottom:

```
📋 Ожидают одобрения:

#{action_id} | Вакансия #{job_raw_id} | {score}/10
  {reason}
  Создано: {created_at}

(если пусто: "Нет вакансий на одобрении")
```

All command handlers must check `is_authorized(message)` first.

Commit: `feat(control_plane): add approval callback + /today /limits /stats commands`

---

## Step 4: Modify scoring worker — add inline keyboard to APPROVAL_REQUIRED

In `capabilities/career_os/skills/match_scoring/worker.py`:

Import at top:
```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
```

Find the APPROVAL_REQUIRED notification block (around line 175). Replace the plain text message with:

```python
elif decision.action_type == ActionType.APPROVAL_REQUIRED:
    # Get the action_id that was just saved
    # (save_action returns rowid — capture it above)
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
```

**IMPORTANT:** Capture the return value of `save_action()` as `action_rowid` — it's needed for callback_data. Currently the code calls save_action but does not capture the return value for the APPROVAL_REQUIRED branch notification. Fix this.

Commit: `feat(scoring): add inline keyboard to APPROVAL_REQUIRED notifications`

---

## Step 5: Register handlers in telegram_bot.py

In `connectors/telegram_bot.py`:

Add imports:
```python
from aiogram.types import CallbackQuery
from capabilities.career_os.skills.control_plane.handlers import (
    handle_approval_callback,
    cmd_today,
    cmd_limits,
    cmd_stats,
)
```

Register handlers BEFORE `dp.start_polling(bot)`:
```python
# Commands
dp.message.register(cmd_today, Command("today"))
dp.message.register(cmd_limits, Command("limits"))
dp.message.register(cmd_stats, Command("stats"))

# Callback queries (inline buttons)
dp.callback_query.register(handle_approval_callback)
```

Alternative (decorator style in handlers.py — choose one, be consistent with existing code).

The existing code uses decorator style (`@dp.message(Command("start"))`). If continuing this pattern, the handlers need access to `dp`. Choose the approach that requires minimal changes.

**Recommended:** Define handlers as plain async functions in handlers.py. Register them in telegram_bot.py using `dp.message.register()` and `dp.callback_query.register()`. This keeps handlers decoupled from the dispatcher.

Commit: `feat(telegram): register approval callback + operator commands`

---

## Step 6: Tests

Create `tests/test_control_plane_store.py`:

Test cases:

```python
# --- get_action_by_id ---
def test_get_action_returns_none_for_missing_id(db_conn)
def test_get_action_returns_dict_for_existing(db_conn)

# --- update_action_status ---
def test_approve_pending_action(db_conn)
    # Insert action with status=pending, action_type=APPROVAL_REQUIRED
    # Call update_action_status(conn, id, 'approved')
    # Assert returns True
    # Assert row.status == 'approved'
    # Assert row.updated_at is not None

def test_reject_pending_action(db_conn)
def test_snooze_pending_action(db_conn)

def test_cannot_approve_already_approved(db_conn)
    # Insert action status=approved
    # Call update_action_status → returns False

def test_cannot_approve_rejected(db_conn)
def test_cannot_reject_snoozed(db_conn)

def test_only_pending_transitions_allowed(db_conn)
    # For each non-pending status: assert update returns False

def test_updated_at_is_set_on_transition(db_conn)
    # Before: updated_at is NULL
    # After approve: updated_at is not NULL

# --- get_today_summary ---
def test_today_summary_empty_db(db_conn)
    # All counts should be 0

def test_today_summary_with_mixed_actions(db_conn)
    # Insert various action types and statuses
    # Verify counts match

# --- get_pending_approvals ---
def test_pending_approvals_empty(db_conn)
def test_pending_approvals_returns_only_pending_approval_required(db_conn)
def test_pending_approvals_excludes_approved(db_conn)

# --- get_policy_display ---
def test_policy_display_defaults(db_conn)
def test_policy_display_with_actions(db_conn)
```

Create `tests/test_control_plane_handlers.py`:

Test the callback parsing and validation logic (unit tests, no actual Telegram):

```python
# Test callback_data parsing
def test_parse_approve_callback()
def test_parse_reject_callback()
def test_parse_snooze_callback()
def test_parse_invalid_callback()
def test_parse_missing_action_id()
```

If testing the full handler flow requires complex mocking of aiogram, write at minimum the store tests and parsing tests. Document what would need integration testing.

Run all tests:
```bash
python3 -m pytest -q
# Expected: 95 existing + ~20 new = ~115 total, all green
```

Commit: `test: add control_plane tests — state transitions, queries, callback parsing`

---

## Step 7: Documentation

### Update `SKILL.md` for control_plane

Replace `capabilities/career_os/skills/control_plane/SKILL.md` with:

```markdown
---
name: control_plane
description: Operator control — approval flow, commands, policy monitoring
---

# Control Plane (v1 — Telegram Approval UX)

## Responsibilities

### Approval Flow
- Receive inline button callbacks (approve/reject/snooze)
- Validate: only APPROVAL_REQUIRED + pending can transition
- Update action status + emit event
- Edit original message to reflect decision

### Operator Commands
- /today — daily summary (ingested, scored, actions by type/status, limit usage)
- /limits — policy thresholds and remaining capacity
- /stats — detailed summary + list of pending approvals

## Authorization
All callbacks and commands check ALLOWED_TELEGRAM_IDS.

## No LLM
All queries are deterministic SQL. No LLM calls.
```

### Update STATUS.md, CHANGELOG.md, DECISIONS.md, BACKLOG.md

**STATUS.md:**
- PR-5: ✅ DONE
- Next: PR-6 (HH Ingest v0.1)

**CHANGELOG.md** — add PR-5 section:
- Added: inline keyboard for APPROVAL_REQUIRED (approve/reject/snooze)
- Added: /today, /limits, /stats commands
- Added: action state transitions (pending → approved/rejected/snoozed)
- Added: migration 005 (updated_at column)
- Added: control_plane handlers and store
- Changed: worker.py APPROVAL_REQUIRED notification includes inline keyboard

**DECISIONS.md** — add PR-5 section:
- Snooze = status marker only; no timer/reminder in MVP
- Callback format: {action}:{action_id}
- Control plane code in control_plane skill, not in scoring worker
- All transitions from pending only; idempotent
- updated_at tracks operator action timestamp

**BACKLOG.md:**
- PR-5: ✅ DONE

Commit: `docs: update STATUS, CHANGELOG, DECISIONS, BACKLOG for PR-5; update SKILL.md`

---

## How to verify

```bash
# Tests
python3 -m pytest -q
# Expected: ~115 tests, all green

# Manual smoke test:
python connectors/telegram_bot.py

# 1. Forward a vacancy that scores >= 7 → expect notification WITH inline buttons
# 2. Press "Одобрить" → expect "✅ Одобрено", message edited, keyboard removed
# 3. Press button again → expect "Уже обработано"
# 4. Type /today → expect daily summary
# 5. Type /limits → expect policy thresholds
# 6. Type /stats → expect summary + pending list
# 7. Check SQLite: SELECT * FROM actions WHERE status = 'approved';
#    Verify updated_at is populated
```

---

## Final Report (write in Russian)

After all steps, generate a report:
1. Что реализовано
2. Какие файлы изменены/созданы
3. Результаты тестов (pytest output)
4. Подтверждение что policy rules не изменены
5. Список рисков или TODO для следующих PR
