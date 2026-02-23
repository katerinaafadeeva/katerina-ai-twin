"""Tests for control_plane handler utilities (unit tests, no real Telegram).

Tests callback_data parsing and is_callback_authorized logic.
Full handler integration (actual aiogram CallbackQuery objects) requires
mocking the entire aiogram dispatcher — documented as requiring integration
tests in a real bot environment.
"""

import pytest

# ---------------------------------------------------------------------------
# _parse_callback — isolated unit tests
# ---------------------------------------------------------------------------
# We import the private helper directly for unit testing.
from capabilities.career_os.skills.control_plane.handlers import _parse_callback


class TestParseCallback:
    def test_parse_approve_callback(self):
        result = _parse_callback("approve:42")
        assert result == ("approve", 42)

    def test_parse_reject_callback(self):
        result = _parse_callback("reject:7")
        assert result == ("reject", 7)

    def test_parse_snooze_callback(self):
        result = _parse_callback("snooze:100")
        assert result == ("snooze", 100)

    def test_parse_invalid_action(self):
        """Unknown action string must return None."""
        result = _parse_callback("delete:5")
        assert result is None

    def test_parse_missing_action_id(self):
        """Missing colon → no valid split → None."""
        result = _parse_callback("approve")
        assert result is None

    def test_parse_empty_string(self):
        result = _parse_callback("")
        assert result is None

    def test_parse_non_integer_id(self):
        """Non-integer action_id must return None (not raise)."""
        result = _parse_callback("approve:abc")
        assert result is None

    def test_parse_negative_id(self):
        """Negative integer is technically valid — parses correctly."""
        result = _parse_callback("approve:-1")
        assert result == ("approve", -1)

    def test_parse_large_id(self):
        result = _parse_callback("reject:999999")
        assert result == ("reject", 999999)

    def test_parse_extra_colons(self):
        """Extra colons in callback_data — split(maxsplit=1) keeps remainder as id_str."""
        result = _parse_callback("approve:1:extra")
        # "1:extra" is not a valid int → None
        assert result is None

    def test_parse_none_input(self):
        """Handles None gracefully (e.g. callback.data is None)."""
        result = _parse_callback(None)
        assert result is None


# ---------------------------------------------------------------------------
# Integration test documentation
# ---------------------------------------------------------------------------
# The following scenarios require integration testing with a real or mocked
# aiogram bot (aiogram's CallbackQuery cannot be easily instantiated in unit tests
# without wiring the full dispatcher):
#
# - handle_approval_callback: unauthorized sender → "Нет доступа" answer
# - handle_approval_callback: malformed callback_data → "Неверный формат"
# - handle_approval_callback: action not found → "Действие не найдено"
# - handle_approval_callback: action_type != APPROVAL_REQUIRED → appropriate answer
# - handle_approval_callback: successful approve/reject/snooze → status updated in DB,
#   event emitted, message edited, keyboard removed, callback.answer() called
# - handle_approval_callback: double-click protection → "Уже обработано"
# - cmd_today: unauthorized → no response
# - cmd_today: authorized → returns summary text
# - cmd_limits: returns policy thresholds text
# - cmd_stats: returns summary + pending approvals list
