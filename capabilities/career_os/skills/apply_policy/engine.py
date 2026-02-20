"""Policy evaluation engine — pure deterministic logic.

No DB access. No LLM. Accepts policy params, score, and source; returns a decision.
All business rules are encoded here and must match SKILL.md + Founder contract.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Possible outcomes of policy evaluation.

    IGNORE:             score below threshold — silent, no notification.
    AUTO_QUEUE:         score in auto range, within daily limit, source = tg/other.
    AUTO_APPLY:         score in auto range, within daily limit, source = hh.
    HOLD:               score in auto range, daily limit reached — held until tomorrow.
    APPROVAL_REQUIRED:  score at or above threshold_high — owner approval needed.
    """

    IGNORE = "IGNORE"
    AUTO_QUEUE = "AUTO_QUEUE"
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
    source: str,
    threshold_low: int,
    threshold_high: int,
    daily_limit: int,
    today_auto_count: int,
) -> PolicyDecision:
    """Evaluate vacancy policy deterministically.

    Pure function — no side effects, no DB access, no LLM calls.

    Boundaries (Founder contract):
    - score < threshold_low          → IGNORE
    - score >= threshold_high        → APPROVAL_REQUIRED  (7 included, not only 8+)
    - score in [threshold_low, threshold_high − 1]:
        - today_auto_count >= daily_limit  → HOLD
        - source == 'hh'                   → AUTO_APPLY
        - else                             → AUTO_QUEUE

    Daily limit counts AUTO_QUEUE + AUTO_APPLY (both types).
    APPROVAL_REQUIRED is NEVER affected by the daily limit.

    Args:
        score: Vacancy score 0–10.
        source: Origin string from job_raw.source ('hh', 'tg', 'telegram_forward', …).
        threshold_low: Score below which vacancy is ignored (default 5).
        threshold_high: Score at or above which approval is required (default 7).
        daily_limit: Max combined AUTO_QUEUE + AUTO_APPLY actions per UTC day (default 40).
        today_auto_count: Number of AUTO_QUEUE + AUTO_APPLY actions already recorded today.

    Returns:
        PolicyDecision with action_type and human-readable reason (Russian).
    """
    if score < threshold_low:
        return PolicyDecision(
            action_type=ActionType.IGNORE,
            reason=f"Оценка {score}/10 ниже порога ({threshold_low})",
        )

    if score >= threshold_high:
        return PolicyDecision(
            action_type=ActionType.APPROVAL_REQUIRED,
            reason=f"Оценка {score}/10 — высокий приоритет, требует вашего одобрения",
        )

    # score in [threshold_low, threshold_high − 1] — auto range
    if today_auto_count >= daily_limit:
        return PolicyDecision(
            action_type=ActionType.HOLD,
            reason=(
                f"Оценка {score}/10 подходит, но дневной лимит исчерпан "
                f"({today_auto_count}/{daily_limit})"
            ),
        )

    new_count = today_auto_count + 1
    if source == "hh":
        return PolicyDecision(
            action_type=ActionType.AUTO_APPLY,
            reason=f"Оценка {score}/10 — автоотклик HH ({new_count}/{daily_limit})",
        )

    return PolicyDecision(
        action_type=ActionType.AUTO_QUEUE,
        reason=f"Оценка {score}/10 — в очередь откликов ({new_count}/{daily_limit})",
    )
