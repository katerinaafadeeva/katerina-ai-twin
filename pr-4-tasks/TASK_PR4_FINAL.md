# TASK: PR-4 — Policy Engine (FINAL — corrected per Founder)

## Role
You are the Implementation Agent (Tech Lead). Execute all steps in order.

## Context
PR-3 (LLM-assisted scoring) is complete and merged. 41 tests pass.
PR-4 adds the policy engine — deterministic routing of scored vacancies.
Branch: `pr4-policy-engine`

**Read these files first:**
- `DECISIONS.md` (score thresholds, policy rules)
- `core/migrations/001_initial.sql` (policy + actions tables)
- `capabilities/career_os/skills/match_scoring/worker.py` (scoring worker — we extend it)
- `capabilities/career_os/skills/match_scoring/store.py` (pattern reference)

**BUSINESS CONTRACT (source of truth):**
- score < 5 → IGNORED (silent, no notification)
- score 5–7 → AUTO_APPLY (auto-apply + cover letter in future PR-5)
- score > 7 (8+) → APPROVAL_REQUIRED (send to owner for approval + cover letter in PR-5)
- score 5–7 + daily limit reached → HOLD (one summary notification per day, NOT per vacancy)

## NO LLM IN THIS PR
Everything is deterministic. No Anthropic calls. Cover letter generation is PR-5.

---

## Step 1: Migration — Extend actions table

Create `core/migrations/004_actions_extend.sql`:

```sql
ALTER TABLE actions ADD COLUMN score INTEGER;
ALTER TABLE actions ADD COLUMN reason TEXT;
ALTER TABLE actions ADD COLUMN actor TEXT DEFAULT 'system';
ALTER TABLE actions ADD COLUMN correlation_id TEXT;
```

Verify: `python -c "from core.db import init_db; init_db(); print('Migration 004 OK')"`

Commit: `feat(core): migration 004 — extend actions with score/reason/actor/correlation_id`

---

## Step 2: Policy engine skill

### Create `capabilities/career_os/skills/apply_policy/__init__.py` — empty

### Create `capabilities/career_os/skills/apply_policy/SKILL.md`

```markdown
---
name: apply_policy
description: Deterministic policy evaluation for scored vacancies
---

# Apply Policy (v1 — Deterministic)

## Input
- job_raw_id (int)
- score (int, 0-10)
- policy record (from policy table)

## Output
- action_type: IGNORED | AUTO_APPLY | HOLD | APPROVAL_REQUIRED
- reason: human-readable string (Russian)

## Business Rules
1. score < threshold_low (5) → IGNORED (silent)
2. score > threshold_high (7), i.e. 8+ → APPROVAL_REQUIRED
3. score in [threshold_low, threshold_high] (5-7):
   a. daily auto count < daily_limit → AUTO_APPLY
   b. daily auto count >= daily_limit → HOLD

## HOLD behavior
- HOLD vacancies get ONE summary notification per day
- Individual HOLD vacancies do NOT trigger notifications
- Summary sent at end of worker cycle if any new HOLDs exist today

## No LLM
This skill is purely deterministic. Cover letter generation is a separate skill (PR-5).
```

### Create `capabilities/career_os/skills/apply_policy/engine.py`

```python
"""Policy evaluation engine — pure deterministic logic.

No DB access. No LLM. Accepts policy params and score, returns decision.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Possible outcomes of policy evaluation.

    IGNORED: score below threshold — no action, no notification.
    AUTO_APPLY: score in auto range, within daily limit — will auto-apply (+ cover letter in PR-5).
    HOLD: score in auto range but daily limit reached — held for next day.
    APPROVAL_REQUIRED: score above threshold — needs owner approval (+ cover letter in PR-5).
    """
    IGNORED = "IGNORED"
    AUTO_APPLY = "AUTO_APPLY"
    HOLD = "HOLD"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass(frozen=True)
class PolicyDecision:
    """Result of policy evaluation."""
    action_type: ActionType
    reason: str


def evaluate_policy(
    score: int,
    threshold_low: int,
    threshold_high: int,
    daily_limit: int,
    today_auto_count: int,
) -> PolicyDecision:
    """Evaluate vacancy policy based on score and current counters.

    Pure function — no side effects, no DB access.

    Args:
        score: Vacancy score (0-10).
        threshold_low: Score below which vacancy is ignored (default 5).
        threshold_high: Score at or below which auto-apply applies (default 7).
                        Scores ABOVE this (8+) require approval.
        daily_limit: Max auto-apply actions per day (default 40).
        today_auto_count: Number of AUTO_APPLY actions already recorded today.

    Returns:
        PolicyDecision with action_type and human-readable reason (Russian).
    """
    if score < threshold_low:
        return PolicyDecision(
            action_type=ActionType.IGNORED,
            reason=f"Оценка {score}/10 ниже порога {threshold_low}",
        )

    if score > threshold_high:
        return PolicyDecision(
            action_type=ActionType.APPROVAL_REQUIRED,
            reason=f"Оценка {score}/10 — высокий приоритет, требует вашего одобрения",
        )

    # Score is in [threshold_low, threshold_high] — auto-apply range
    if today_auto_count >= daily_limit:
        return PolicyDecision(
            action_type=ActionType.HOLD,
            reason=f"Оценка {score}/10 подходит, но лимит на сегодня исчерпан ({today_auto_count}/{daily_limit})",
        )

    return PolicyDecision(
        action_type=ActionType.AUTO_APPLY,
        reason=f"Оценка {score}/10 — автоотклик ({today_auto_count + 1}/{daily_limit})",
    )
```

### Create `capabilities/career_os/skills/apply_policy/store.py`

```python
"""Persistence for policy decisions (actions table) and daily counters."""

import logging
import sqlite3
from typing import Optional

from capabilities.career_os.skills.apply_policy.engine import PolicyDecision

logger = logging.getLogger(__name__)


def get_policy(conn: sqlite3.Connection) -> dict:
    """Read the current policy record.

    Returns dict with threshold_low, threshold_high, daily_limit.
    Falls back to safe defaults if no row exists.
    """
    row = conn.execute("SELECT * FROM policy WHERE id = 1").fetchone()
    if row is None:
        logger.warning("No policy row found — using defaults")
        return {"threshold_low": 5, "threshold_high": 7, "daily_limit": 40}
    return dict(row)


def get_today_auto_count(conn: sqlite3.Connection) -> int:
    """Count AUTO_APPLY actions created today (UTC).

    Only counts AUTO_APPLY, not HOLD or other types.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM actions
        WHERE action_type = 'AUTO_APPLY'
        AND date(created_at) = date('now')
        """
    ).fetchone()
    return row["cnt"] if row else 0


def get_today_hold_count(conn: sqlite3.Connection) -> int:
    """Count HOLD actions created today (UTC)."""
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM actions
        WHERE action_type = 'HOLD'
        AND date(created_at) = date('now')
        """
    ).fetchone()
    return row["cnt"] if row else 0


def was_hold_notification_sent_today(conn: sqlite3.Connection) -> bool:
    """Check if a hold summary notification event was already sent today.

    Uses the events table — looks for a 'policy.hold_summary' event today.
    """
    row = conn.execute(
        """
        SELECT 1 FROM events
        WHERE event_name = 'policy.hold_summary'
        AND date(created_at) = date('now')
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def save_action(
    conn: sqlite3.Connection,
    job_raw_id: int,
    decision: PolicyDecision,
    score: int,
    actor: str = "policy_engine",
    correlation_id: Optional[str] = None,
) -> int:
    """Persist a policy decision to the actions table.

    Returns row-id of the inserted action.
    """
    cursor = conn.execute(
        """
        INSERT INTO actions (job_raw_id, action_type, status, score, reason, actor, correlation_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_raw_id,
            decision.action_type.value,
            "created",
            score,
            decision.reason,
            actor,
            correlation_id,
        ),
    )
    logger.info(
        "Policy applied",
        extra={
            "job_raw_id": job_raw_id,
            "action_type": decision.action_type.value,
            "score": score,
        },
    )
    return cursor.lastrowid
```

Commit: `feat(career_os): add policy engine — deterministic routing (AUTO_APPLY/HOLD/APPROVAL_REQUIRED/IGNORED)`

---

## Step 3: Integrate into scoring worker

Modify `capabilities/career_os/skills/match_scoring/worker.py`.

Add these imports at the top:
```python
from capabilities.career_os.skills.apply_policy.engine import ActionType, evaluate_policy
from capabilities.career_os.skills.apply_policy.store import (
    get_policy,
    get_today_auto_count,
    get_today_hold_count,
    save_action,
    was_hold_notification_sent_today,
)
```

Inside the worker loop, **after** `save_score(...)`, `conn.commit()`, and `emit("vacancy.scored", ...)`, add:

```python
                    # --- Policy evaluation (deterministic, no LLM) ---
                    with get_conn() as policy_conn:
                        policy = get_policy(policy_conn)
                        today_count = get_today_auto_count(policy_conn)

                        decision = evaluate_policy(
                            score=result.score,
                            threshold_low=policy["threshold_low"],
                            threshold_high=policy["threshold_high"],
                            daily_limit=policy["daily_limit"],
                            today_auto_count=today_count,
                        )

                        save_action(
                            policy_conn,
                            job_raw_id=job_raw_id,
                            decision=decision,
                            score=result.score,
                            actor="policy_engine",
                            correlation_id=correlation_id,
                        )
                        policy_conn.commit()

                    emit(
                        "vacancy.policy_applied",
                        {
                            "job_raw_id": job_raw_id,
                            "score": result.score,
                            "action_type": decision.action_type.value,
                        },
                        actor="policy_engine",
                        correlation_id=correlation_id,
                    )

                    # --- Telegram notification ---
                    if config.allowed_telegram_ids:
                        chat_id = config.allowed_telegram_ids[0]
                        emoji = _score_emoji(result.score)

                        if decision.action_type == ActionType.IGNORED:
                            pass  # Silent — no notification

                        elif decision.action_type == ActionType.HOLD:
                            pass  # Individual HOLDs are silent; summary sent below

                        elif decision.action_type == ActionType.AUTO_APPLY:
                            await bot.send_message(
                                chat_id,
                                f"Оценка #{job_raw_id}: {emoji} {result.score}/10\n"
                                f"{result.explanation}\n\n"
                                f"📋 Автоотклик ({today_count + 1}/{policy['daily_limit']})",
                            )

                        elif decision.action_type == ActionType.APPROVAL_REQUIRED:
                            await bot.send_message(
                                chat_id,
                                f"Оценка #{job_raw_id}: {emoji} {result.score}/10\n"
                                f"{result.explanation}\n\n"
                                f"👀 Требует вашего одобрения",
                            )
```

**Remove** the old notification block that was there before (the simple one with just score+emoji).

After the `for vacancy in unscored:` loop ends (but still inside the outer `try`), add the HOLD summary:

```python
            # --- HOLD summary notification (once per day) ---
            if config.allowed_telegram_ids:
                with get_conn() as hold_conn:
                    hold_count = get_today_hold_count(hold_conn)
                    already_notified = was_hold_notification_sent_today(hold_conn)

                if hold_count > 0 and not already_notified:
                    chat_id = config.allowed_telegram_ids[0]
                    await bot.send_message(
                        chat_id,
                        f"⚠️ {hold_count} вакансий в холде — дневной лимит исчерпан.\n"
                        f"Они будут обработаны завтра или при увеличении лимита.",
                    )
                    emit(
                        "policy.hold_summary",
                        {"hold_count": hold_count},
                        actor="policy_engine",
                    )
```

Commit: `feat(scoring): integrate policy engine — AUTO_APPLY/HOLD/APPROVAL routing + notifications`

---

## Step 4: Tests

### Create `tests/test_policy_engine.py`

```python
"""Tests for apply_policy/engine.py — pure deterministic logic."""

import pytest
from capabilities.career_os.skills.apply_policy.engine import (
    ActionType,
    evaluate_policy,
)


# --- IGNORED ---

def test_score_0_ignored():
    r = evaluate_policy(score=0, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.IGNORED

def test_score_4_ignored():
    r = evaluate_policy(score=4, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.IGNORED

def test_score_below_custom_threshold_ignored():
    r = evaluate_policy(score=2, threshold_low=3, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.IGNORED


# --- AUTO_APPLY ---

def test_score_5_auto_apply():
    """Boundary: threshold_low inclusive."""
    r = evaluate_policy(score=5, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.AUTO_APPLY

def test_score_6_auto_apply():
    r = evaluate_policy(score=6, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=10)
    assert r.action_type == ActionType.AUTO_APPLY

def test_score_7_auto_apply():
    """Boundary: threshold_high inclusive for auto range."""
    r = evaluate_policy(score=7, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.AUTO_APPLY

def test_auto_apply_one_below_limit():
    r = evaluate_policy(score=6, threshold_low=5, threshold_high=7, daily_limit=10, today_auto_count=9)
    assert r.action_type == ActionType.AUTO_APPLY


# --- HOLD ---

def test_hold_when_limit_reached():
    r = evaluate_policy(score=6, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=40)
    assert r.action_type == ActionType.HOLD

def test_hold_at_exact_limit():
    r = evaluate_policy(score=5, threshold_low=5, threshold_high=7, daily_limit=10, today_auto_count=10)
    assert r.action_type == ActionType.HOLD

def test_hold_over_limit():
    r = evaluate_policy(score=7, threshold_low=5, threshold_high=7, daily_limit=5, today_auto_count=100)
    assert r.action_type == ActionType.HOLD


# --- APPROVAL_REQUIRED ---

def test_score_8_approval():
    """Boundary: strictly above threshold_high."""
    r = evaluate_policy(score=8, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.APPROVAL_REQUIRED

def test_score_10_approval():
    r = evaluate_policy(score=10, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=0)
    assert r.action_type == ActionType.APPROVAL_REQUIRED

def test_approval_ignores_daily_limit():
    """APPROVAL_REQUIRED is not affected by daily limit."""
    r = evaluate_policy(score=9, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=999)
    assert r.action_type == ActionType.APPROVAL_REQUIRED


# --- Reason text ---

def test_reason_contains_score():
    r = evaluate_policy(score=6, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=5)
    assert "6/10" in r.reason

def test_hold_reason_contains_limit():
    r = evaluate_policy(score=6, threshold_low=5, threshold_high=7, daily_limit=40, today_auto_count=40)
    assert "40/40" in r.reason
```

### Create `tests/test_policy_store.py`

```python
"""Tests for apply_policy/store.py — actions persistence and counters."""

from capabilities.career_os.skills.apply_policy.engine import ActionType, PolicyDecision
from capabilities.career_os.skills.apply_policy.store import (
    get_policy,
    get_today_auto_count,
    get_today_hold_count,
    save_action,
    was_hold_notification_sent_today,
)


def _insert_vacancy(conn, job_id=1):
    conn.execute(
        "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (?, 'text', 'tg', ?)",
        (job_id, f"src_{job_id}"),
    )
    conn.commit()


def test_get_policy_defaults(db_conn):
    p = get_policy(db_conn)
    assert p["threshold_low"] == 5
    assert p["threshold_high"] == 7
    assert p["daily_limit"] == 40


def test_get_policy_custom(db_conn):
    db_conn.execute("UPDATE policy SET threshold_low=3, threshold_high=8, daily_limit=20 WHERE id=1")
    db_conn.commit()
    p = get_policy(db_conn)
    assert p["threshold_low"] == 3
    assert p["daily_limit"] == 20


def test_today_auto_count_zero(db_conn):
    assert get_today_auto_count(db_conn) == 0


def test_today_auto_count_after_save(db_conn):
    _insert_vacancy(db_conn)
    d = PolicyDecision(ActionType.AUTO_APPLY, "test")
    save_action(db_conn, 1, d, score=6)
    db_conn.commit()
    assert get_today_auto_count(db_conn) == 1


def test_hold_not_counted_as_auto(db_conn):
    _insert_vacancy(db_conn)
    d = PolicyDecision(ActionType.HOLD, "test")
    save_action(db_conn, 1, d, score=6)
    db_conn.commit()
    assert get_today_auto_count(db_conn) == 0
    assert get_today_hold_count(db_conn) == 1


def test_ignored_not_counted(db_conn):
    _insert_vacancy(db_conn)
    d = PolicyDecision(ActionType.IGNORED, "test")
    save_action(db_conn, 1, d, score=3)
    db_conn.commit()
    assert get_today_auto_count(db_conn) == 0
    assert get_today_hold_count(db_conn) == 0


def test_save_action_persists_fields(db_conn):
    _insert_vacancy(db_conn)
    d = PolicyDecision(ActionType.AUTO_APPLY, "Автоотклик 6/10")
    rowid = save_action(db_conn, 1, d, score=6, correlation_id="uuid-123")
    db_conn.commit()
    row = dict(db_conn.execute("SELECT * FROM actions WHERE id=?", (rowid,)).fetchone())
    assert row["action_type"] == "AUTO_APPLY"
    assert row["score"] == 6
    assert row["reason"] == "Автоотклик 6/10"
    assert row["correlation_id"] == "uuid-123"
    assert row["status"] == "created"


def test_hold_notification_not_sent_initially(db_conn):
    assert was_hold_notification_sent_today(db_conn) is False


def test_hold_notification_detected_after_event(db_conn):
    db_conn.execute(
        "INSERT INTO events (event_name, payload_json, actor) VALUES ('policy.hold_summary', '{}', 'policy_engine')"
    )
    db_conn.commit()
    assert was_hold_notification_sent_today(db_conn) is True
```

Commit: `test: add policy engine tests — all routing branches, counters, HOLD summary`

---

## Step 5: Documentation

### Update `STATUS.md`
- PR-4: ✅ DONE
- Next: PR-5 (Cover letter generation + Telegram approval UX)

### Update `DECISIONS.md` — add:
```
## PR-4 Decisions

### Action types (per Founder business contract)
- IGNORED: score < 5 — silent
- AUTO_APPLY: score 5-7, within daily limit — auto-apply + cover letter (PR-5)
- HOLD: score 5-7, daily limit reached — held, one summary notification/day
- APPROVAL_REQUIRED: score 8+ — sent to Founder for approval + cover letter (PR-5)

### Policy engine inline in scoring worker
Policy evaluation runs synchronously after scoring. <1ms deterministic logic.

### HOLD notification: one per day
Individual HOLD vacancies do NOT trigger notifications.
One summary ("N вакансий в холде") at end of worker cycle, max once per day.
Tracked via policy.hold_summary event in events table.
```

### Update `CHANGELOG.md` — add PR-4 section

### Update `BACKLOG.md` — PR-3 DONE, PR-4 DONE

### Clean stale docs:
- `docs/CHAT_HANDOFF.md` — update current phase
- `docs/TOKEN_BUDGET.md` — note LLM scoring approved since PR-3

Commit: `docs: update STATUS, DECISIONS, CHANGELOG, BACKLOG for PR-4; clean stale docs`

---

## How to verify

```bash
pytest -v
# Expected: all existing 41 tests + new ~18 policy tests = ~59 total, all green

# Manual smoke test:
python connectors/telegram_bot.py
# Forward vacancy → expect score notification WITH action label
# Forward low-score vacancy → expect NO notification (IGNORED)
# Check SQLite: SELECT * FROM actions ORDER BY id DESC LIMIT 5;
```
