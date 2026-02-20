"""Tests for capabilities/career_os/skills/apply_policy/engine.py.

Verifies all routing branches per Founder contract:
- score < threshold_low (5) → IGNORE
- score in [5, 6], within limit, source='hh' → AUTO_APPLY
- score in [5, 6], within limit, source='tg' → AUTO_QUEUE
- score in [5, 6], limit reached → HOLD
- score >= threshold_high (7) → APPROVAL_REQUIRED (7 included, not only 8+)

APPROVAL_REQUIRED is never affected by daily limit.
"""

from capabilities.career_os.skills.apply_policy.engine import (
    ActionType,
    PolicyDecision,
    evaluate_policy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULTS = dict(
    threshold_low=5,
    threshold_high=7,
    daily_limit=40,
    today_auto_count=0,
)


def _eval(score: int, source: str = "tg", **overrides) -> PolicyDecision:
    """Shorthand: call evaluate_policy with default params, allow overrides."""
    params = {**_DEFAULTS, **overrides}
    return evaluate_policy(score=score, source=source, **params)


# ---------------------------------------------------------------------------
# IGNORE — score below threshold_low
# ---------------------------------------------------------------------------


class TestIgnore:
    def test_score_zero(self):
        d = _eval(0)
        assert d.action_type == ActionType.IGNORE

    def test_score_4(self):
        d = _eval(4)
        assert d.action_type == ActionType.IGNORE

    def test_score_below_custom_low(self):
        d = _eval(3, threshold_low=4, threshold_high=7)
        assert d.action_type == ActionType.IGNORE

    def test_score_4_boundary_below_5(self):
        """Score 4 is strictly below threshold_low=5 → IGNORE."""
        d = _eval(4, threshold_low=5)
        assert d.action_type == ActionType.IGNORE

    def test_ignore_reason_contains_score(self):
        d = _eval(3)
        assert "3" in d.reason


# ---------------------------------------------------------------------------
# AUTO_APPLY — hh source, within limit
# ---------------------------------------------------------------------------


class TestAutoApply:
    def test_score_5_hh(self):
        d = _eval(5, source="hh")
        assert d.action_type == ActionType.AUTO_APPLY

    def test_score_6_hh(self):
        d = _eval(6, source="hh")
        assert d.action_type == ActionType.AUTO_APPLY

    def test_score_6_hh_limit_not_reached(self):
        d = _eval(6, source="hh", today_auto_count=39, daily_limit=40)
        assert d.action_type == ActionType.AUTO_APPLY

    def test_auto_apply_reason_contains_count(self):
        d = _eval(5, source="hh", today_auto_count=10, daily_limit=40)
        assert "11" in d.reason  # new_count = 10 + 1


# ---------------------------------------------------------------------------
# AUTO_QUEUE — non-hh source, within limit
# ---------------------------------------------------------------------------


class TestAutoQueue:
    def test_score_5_tg(self):
        d = _eval(5, source="tg")
        assert d.action_type == ActionType.AUTO_QUEUE

    def test_score_6_tg(self):
        d = _eval(6, source="tg")
        assert d.action_type == ActionType.AUTO_QUEUE

    def test_score_5_telegram_forward(self):
        d = _eval(5, source="telegram_forward")
        assert d.action_type == ActionType.AUTO_QUEUE

    def test_score_5_other_source(self):
        d = _eval(5, source="other")
        assert d.action_type == ActionType.AUTO_QUEUE

    def test_auto_queue_reason_contains_count(self):
        d = _eval(6, source="tg", today_auto_count=5, daily_limit=40)
        assert "6" in d.reason  # new_count = 5 + 1


# ---------------------------------------------------------------------------
# HOLD — daily limit reached
# ---------------------------------------------------------------------------


class TestHold:
    def test_limit_exact_tg(self):
        """When today_auto_count == daily_limit, route to HOLD."""
        d = _eval(5, source="tg", today_auto_count=40, daily_limit=40)
        assert d.action_type == ActionType.HOLD

    def test_limit_exceeded_hh(self):
        """Even hh source goes to HOLD when limit is reached."""
        d = _eval(6, source="hh", today_auto_count=40, daily_limit=40)
        assert d.action_type == ActionType.HOLD

    def test_limit_over_exceeded(self):
        d = _eval(5, source="tg", today_auto_count=99, daily_limit=40)
        assert d.action_type == ActionType.HOLD

    def test_hold_reason_contains_counts(self):
        d = _eval(5, today_auto_count=40, daily_limit=40)
        assert "40" in d.reason

    def test_hold_boundary_one_below_triggers_auto(self):
        """One below the limit should still route to AUTO_QUEUE."""
        d = _eval(5, source="tg", today_auto_count=39, daily_limit=40)
        assert d.action_type == ActionType.AUTO_QUEUE


# ---------------------------------------------------------------------------
# APPROVAL_REQUIRED — score >= threshold_high (7 included, not only 8+)
# ---------------------------------------------------------------------------


class TestApprovalRequired:
    def test_score_7(self):
        """Score 7 must be APPROVAL_REQUIRED — not AUTO_QUEUE or AUTO_APPLY."""
        d = _eval(7)
        assert d.action_type == ActionType.APPROVAL_REQUIRED

    def test_score_8(self):
        d = _eval(8)
        assert d.action_type == ActionType.APPROVAL_REQUIRED

    def test_score_10(self):
        d = _eval(10)
        assert d.action_type == ActionType.APPROVAL_REQUIRED

    def test_approval_not_blocked_by_limit(self):
        """APPROVAL_REQUIRED must never be routed to HOLD even if daily limit reached."""
        d = _eval(7, today_auto_count=9999, daily_limit=40)
        assert d.action_type == ActionType.APPROVAL_REQUIRED

    def test_approval_not_blocked_hh_limit(self):
        d = _eval(8, source="hh", today_auto_count=9999, daily_limit=40)
        assert d.action_type == ActionType.APPROVAL_REQUIRED

    def test_approval_reason_contains_score(self):
        d = _eval(7)
        assert "7" in d.reason

    def test_custom_threshold_high(self):
        """With threshold_high=8, score 7 stays in auto range."""
        d = _eval(7, threshold_low=5, threshold_high=8, today_auto_count=0)
        assert d.action_type == ActionType.AUTO_QUEUE


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


def test_returns_policy_decision():
    d = _eval(5)
    assert isinstance(d, PolicyDecision)
    assert isinstance(d.action_type, ActionType)
    assert isinstance(d.reason, str)
    assert len(d.reason) > 0
