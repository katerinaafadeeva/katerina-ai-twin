"""Tests for match_scoring pre_filter module."""
import pytest
from capabilities.career_os.skills.match_scoring.pre_filter import should_skip_scoring


def test_pre_filter_rejects_intern():
    skip, reason = should_skip_scoring("Стажёр в отдел маркетинга, работа с документами и отчётностью")
    assert skip is True
    assert "keyword_reject" in reason


def test_pre_filter_rejects_stazher():
    skip, reason = should_skip_scoring("Стажер продавца в розничном магазине, опыт не требуется")
    assert skip is True
    assert "keyword_reject" in reason


def test_pre_filter_rejects_driver():
    skip, reason = should_skip_scoring("Водитель грузового автомобиля, опыт от 3 лет, категория C")
    assert skip is True
    assert "keyword_reject" in reason


def test_pre_filter_allows_product_manager():
    skip, reason = should_skip_scoring(
        "Позиция: Product Manager\nКомпания: ACME\nОпыт 3+ лет управления продуктом"
    )
    assert skip is False


def test_pre_filter_allows_junior_pm():
    skip, reason = should_skip_scoring(
        "Junior Product Manager в стартап, опыт работы с backlog"
    )
    assert skip is False


def test_pre_filter_too_short_text():
    skip, reason = should_skip_scoring("PM")
    assert skip is True
    assert reason == "too_short"


def test_pre_filter_empty_text():
    skip, reason = should_skip_scoring("")
    assert skip is True
    assert reason == "too_short"
