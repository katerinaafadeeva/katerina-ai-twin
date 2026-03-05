"""Tests for day-of-week apply cap logic.

Covers:
- _get_effective_apply_cap: correct cap for each weekday (Mon-Sun)
- _WEEKDAY_CAP_MULTIPLIERS: sanity checks on the table values
- Edge cases: apply_daily_cap=0 (no cap), apply_daily_cap=1
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# Module path for patching datetime inside the worker
_W = "capabilities.career_os.skills.hh_apply.worker"


def _mock_utc(year=2026, month=3, day=1, hour=12, weekday_offset=0):
    """Return a fixed UTC datetime. day=3 (Mon) + weekday_offset shifts the day."""
    # 2026-03-02 is Monday (weekday=0)
    # 2026-03-03 Tue, 2026-03-04 Wed, 2026-03-05 Thu, 2026-03-06 Fri, 2026-03-07 Sat, 2026-03-08 Sun
    _WEEKDAY_DATES = {
        0: datetime(2026, 3, 2, hour, 0, 0, tzinfo=timezone.utc),   # Mon
        1: datetime(2026, 3, 3, hour, 0, 0, tzinfo=timezone.utc),   # Tue
        2: datetime(2026, 3, 4, hour, 0, 0, tzinfo=timezone.utc),   # Wed
        3: datetime(2026, 3, 5, hour, 0, 0, tzinfo=timezone.utc),   # Thu
        4: datetime(2026, 3, 6, hour, 0, 0, tzinfo=timezone.utc),   # Fri
        5: datetime(2026, 3, 7, hour, 0, 0, tzinfo=timezone.utc),   # Sat
        6: datetime(2026, 3, 8, hour, 0, 0, tzinfo=timezone.utc),   # Sun
    }
    return _WEEKDAY_DATES[weekday_offset]


# ---------------------------------------------------------------------------
# _WEEKDAY_CAP_MULTIPLIERS — sanity checks
# ---------------------------------------------------------------------------


class TestWeekdayCapMultipliersTable:
    def test_all_seven_days_present(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        assert set(_WEEKDAY_CAP_MULTIPLIERS.keys()) == {0, 1, 2, 3, 4, 5, 6}

    def test_peak_days_are_1(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        for day in (1, 2, 3):  # Tue, Wed, Thu
            assert _WEEKDAY_CAP_MULTIPLIERS[day] == 1.0, f"weekday {day} should be peak (1.0)"

    def test_monday_is_half(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        assert _WEEKDAY_CAP_MULTIPLIERS[0] == 0.5

    def test_friday_is_twenty_percent(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        assert _WEEKDAY_CAP_MULTIPLIERS[4] == 0.2

    def test_weekend_is_zero(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        assert _WEEKDAY_CAP_MULTIPLIERS[5] == 0.0  # Sat
        assert _WEEKDAY_CAP_MULTIPLIERS[6] == 0.0  # Sun

    def test_all_multipliers_in_range(self):
        from capabilities.career_os.skills.hh_apply.worker import _WEEKDAY_CAP_MULTIPLIERS
        for day, mult in _WEEKDAY_CAP_MULTIPLIERS.items():
            assert 0.0 <= mult <= 1.0, f"weekday {day} multiplier {mult} out of [0, 1]"


# ---------------------------------------------------------------------------
# _get_effective_apply_cap — per-day values with peak_cap=40
# ---------------------------------------------------------------------------


class TestGetEffectiveApplyCap:
    def _cap(self, weekday: int, peak: int = 40) -> int:
        """Helper: call _get_effective_apply_cap with mocked weekday and config."""
        from capabilities.career_os.skills.hh_apply import worker as w
        mock_cfg = type("C", (), {"apply_daily_cap": peak})()
        mocked_dt = _mock_utc(weekday_offset=weekday)
        with patch(f"{_W}.config", mock_cfg), \
             patch(f"{_W}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mocked_dt
            return w._get_effective_apply_cap()

    def test_monday_is_20(self):
        assert self._cap(0) == 20  # 40 * 0.5

    def test_tuesday_is_40(self):
        assert self._cap(1) == 40  # 40 * 1.0

    def test_wednesday_is_40(self):
        assert self._cap(2) == 40

    def test_thursday_is_40(self):
        assert self._cap(3) == 40

    def test_friday_is_8(self):
        assert self._cap(4) == 8   # 40 * 0.2

    def test_saturday_is_0(self):
        assert self._cap(5) == 0

    def test_sunday_is_0(self):
        assert self._cap(6) == 0

    def test_no_cap_mode_returns_0(self):
        """apply_daily_cap=0 means no cap — always return 0 (passthrough)."""
        assert self._cap(1, peak=0) == 0   # Tue peak but cap disabled
        assert self._cap(3, peak=0) == 0   # Thu peak but cap disabled

    def test_cap_1_monday_rounds_to_1(self):
        """peak=1 on Monday: round(1 * 0.5) = 1 (not 0)."""
        assert self._cap(0, peak=1) == round(1 * 0.5)

    def test_cap_10_friday_is_2(self):
        """peak=10 on Friday: round(10 * 0.2) = 2."""
        assert self._cap(4, peak=10) == 2

    def test_cap_3_friday_rounds_correctly(self):
        """peak=3 on Friday: round(3 * 0.2) = round(0.6) = 1."""
        assert self._cap(4, peak=3) == round(3 * 0.2)
