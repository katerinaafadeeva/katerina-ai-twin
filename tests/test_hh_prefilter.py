"""Tests for capabilities/career_os/skills/vacancy_ingest_hh/prefilter.py.

Covers:
- Clean vacancy passes all filters
- Negative signal rejection (case-insensitive)
- Excluded industry rejection (case-insensitive)
- Empty profile signals pass all vacancies
- Reason string returned on rejection
"""

import pytest

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.prefilter import should_score


def _make_profile(
    negative_signals: tuple = (),
    industries_excluded: tuple = (),
) -> Profile:
    """Minimal Profile with configurable filter fields."""
    return Profile(
        target_roles=("Product Manager",),
        target_seniority=("senior",),
        work_format=("remote",),
        geo_cities=("Москва",),
        relocation=False,
        salary_min=200_000,
        salary_currency="RUB",
        required_skills=("product management",),
        bonus_skills=(),
        negative_signals=negative_signals,
        industries_preferred=(),
        industries_excluded=industries_excluded,
        languages=("Russian",),
    )


CLEAN_VACANCY = "Позиция: Product Manager\nКомпания: Tech Corp\nФормат: удалённая работа"


class TestShouldScoreClean:
    def test_clean_vacancy_passes(self):
        profile = _make_profile(
            negative_signals=("MLM", "холодные звонки"),
            industries_excluded=("азартные игры",),
        )
        passes, reason = should_score(CLEAN_VACANCY, profile)
        assert passes is True
        assert reason == ""

    def test_empty_negative_signals_passes(self):
        profile = _make_profile(negative_signals=(), industries_excluded=())
        passes, reason = should_score(CLEAN_VACANCY, profile)
        assert passes is True

    def test_empty_excluded_industries_passes(self):
        profile = _make_profile(negative_signals=("MLM",), industries_excluded=())
        passes, reason = should_score(CLEAN_VACANCY, profile)
        assert passes is True


class TestNegativeSignals:
    def test_rejects_negative_signal_exact(self):
        profile = _make_profile(negative_signals=("MLM",))
        vacancy = "Позиция: менеджер MLM сеть"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert "MLM" in reason

    def test_rejects_negative_signal_case_insensitive(self):
        profile = _make_profile(negative_signals=("холодные звонки",))
        vacancy = "Обязанности: ХОЛОДНЫЕ ЗВОНКИ клиентам"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert "холодные звонки" in reason.lower()

    def test_rejects_negative_signal_substring(self):
        profile = _make_profile(negative_signals=("MLM",))
        vacancy = "Позиция: менеджер (mlm-компания)"
        passes, reason = should_score(vacancy, profile)
        assert passes is False

    def test_reason_contains_signal_name(self):
        profile = _make_profile(negative_signals=("cold calling",))
        vacancy = "Requirements: cold calling experience required"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert "negative_signal" in reason
        assert "cold calling" in reason

    def test_multiple_signals_first_match_wins(self):
        profile = _make_profile(negative_signals=("MLM", "казино"))
        vacancy = "Продавец MLM"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert "MLM" in reason


class TestExcludedIndustries:
    def test_rejects_excluded_industry(self):
        profile = _make_profile(industries_excluded=("gambling",))
        vacancy = "Позиция: PM\nСфера: online gambling platform"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert "excluded_industry" in reason
        assert "gambling" in reason

    def test_rejects_excluded_industry_case_insensitive(self):
        profile = _make_profile(industries_excluded=("казино",))
        vacancy = "Работодатель: КАЗИНО ВегасПлюс"
        passes, reason = should_score(vacancy, profile)
        assert passes is False

    def test_reason_format_for_industry(self):
        profile = _make_profile(industries_excluded=("азартные игры",))
        vacancy = "Компания: Азартные Игры ООО"
        passes, reason = should_score(vacancy, profile)
        assert passes is False
        assert reason.startswith("excluded_industry:")


class TestReturnTypes:
    def test_returns_tuple_of_bool_and_str(self):
        profile = _make_profile()
        result = should_score(CLEAN_VACANCY, profile)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_pass_returns_empty_reason(self):
        profile = _make_profile()
        _, reason = should_score(CLEAN_VACANCY, profile)
        assert reason == ""

    def test_reject_returns_non_empty_reason(self):
        profile = _make_profile(negative_signals=("MLM",))
        _, reason = should_score("MLM схема", profile)
        assert len(reason) > 0
