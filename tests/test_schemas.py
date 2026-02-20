"""Tests for core/llm/schemas.py — ScoringOutput validation."""

import pytest
from pydantic import ValidationError

from core.llm.schemas import ScoreReason, ScoringOutput

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_REASON = {"criterion": "role_match", "matched": True, "note": "совпадение"}
_VALID_EXPLANATION = "Хорошее совпадение по роли и формату работы."


def _make(**overrides) -> dict:
    base = {
        "score": 7,
        "reasons": [_VALID_REASON],
        "explanation": _VALID_EXPLANATION,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Score range
# ---------------------------------------------------------------------------


def test_score_valid_boundaries():
    for score in (0, 5, 10):
        out = ScoringOutput(**_make(score=score))
        assert out.score == score


def test_score_rejects_negative():
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(score=-1))


def test_score_rejects_above_10():
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(score=11))


def test_score_rejects_100():
    """Explicit: old 0-100 scale must be rejected."""
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(score=100))


# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------


def test_reasons_rejects_empty_list():
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(reasons=[]))


def test_reasons_accepts_multiple():
    reasons = [
        {"criterion": "role_match", "matched": True, "note": "совпадение"},
        {"criterion": "format_match", "matched": False, "note": "офис"},
    ]
    out = ScoringOutput(**_make(reasons=reasons))
    assert len(out.reasons) == 2


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


def test_explanation_rejects_too_short():
    # min_length=10 in schema
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(explanation="Нет."))


def test_explanation_rejects_empty():
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(explanation=""))


def test_explanation_accepts_exactly_10_chars():
    out = ScoringOutput(**_make(explanation="0123456789"))
    assert len(out.explanation) == 10


def test_explanation_rejects_above_500_chars():
    with pytest.raises(ValidationError):
        ScoringOutput(**_make(explanation="x" * 501))
