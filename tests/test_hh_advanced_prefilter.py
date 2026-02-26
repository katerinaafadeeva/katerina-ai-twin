"""Tests for capabilities/career_os/skills/vacancy_ingest_hh/filters.py.

Covers:
- should_score_advanced: missing filters file → passes (all vacancies allowed)
- should_score_advanced: salary below floor → rejected
- should_score_advanced: salary above floor → passes
- should_score_advanced: no salary + allow_no_salary=false → rejected
- should_score_advanced: no salary + allow_no_salary=true → passes
- should_score_advanced: exclude_keyword present → rejected
- should_score_advanced: required_keywords_any — no match → rejected
- should_score_advanced: required_keywords_any — match found → passes
"""

import json
import pytest


def _write_filters(path, data):
    """Helper: write a filters JSON file."""
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers — reset module cache between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_filters_cache():
    """Clear module-level cache before each test to isolate file loading."""
    import capabilities.career_os.skills.vacancy_ingest_hh.filters as f
    f._filters_cache.clear()
    yield
    f._filters_cache.clear()


# ---------------------------------------------------------------------------
# should_score_advanced — unit tests
# ---------------------------------------------------------------------------


class TestShouldScoreAdvanced:
    def test_missing_filters_file_passes(self, tmp_path):
        """No hh_filters.json → all vacancies pass (advanced filter disabled)."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        nonexistent = str(tmp_path / "hh_filters.json")
        passes, reason = should_score_advanced(
            vacancy_text="Senior Product Manager at Yandex",
            salary_min=100_000,
            salary_currency="RUR",
            has_salary=True,
            filters_path=nonexistent,
        )
        assert passes is True
        assert reason == ""

    def test_salary_below_floor_rejected(self, tmp_path):
        """Salary below min_salary_rub → rejected."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(filters_file, {"min_salary_rub": 150_000, "allow_no_salary": True})

        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=100_000,
            salary_currency="RUR",
            has_salary=True,
            filters_path=str(filters_file),
        )
        assert passes is False
        assert "salary_below_floor" in reason
        assert "100000" in reason

    def test_salary_above_floor_passes(self, tmp_path):
        """Salary at or above min_salary_rub → passes."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(filters_file, {"min_salary_rub": 150_000, "allow_no_salary": True})

        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=200_000,
            salary_currency="RUR",
            has_salary=True,
            filters_path=str(filters_file),
        )
        assert passes is True
        assert reason == ""

    def test_no_salary_not_allowed_rejected(self, tmp_path):
        """has_salary=False + allow_no_salary=False → rejected."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(
            filters_file, {"min_salary_rub": 150_000, "allow_no_salary": False}
        )

        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=None,
            salary_currency="",
            has_salary=False,
            filters_path=str(filters_file),
        )
        assert passes is False
        assert "no_salary_not_allowed" in reason

    def test_no_salary_allowed_passes(self, tmp_path):
        """has_salary=False + allow_no_salary=True → passes salary check."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(
            filters_file, {"min_salary_rub": 150_000, "allow_no_salary": True}
        )

        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=None,
            salary_currency="",
            has_salary=False,
            filters_path=str(filters_file),
        )
        assert passes is True
        assert reason == ""

    def test_exclude_keyword_rejected(self, tmp_path):
        """Vacancy text contains an excluded keyword → rejected."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(
            filters_file, {"exclude_keywords": ["стажёр", "intern"]}
        )

        passes, reason = should_score_advanced(
            vacancy_text="Стажёр-аналитик в команду роста",
            salary_min=None,
            salary_currency="",
            has_salary=False,
            filters_path=str(filters_file),
        )
        assert passes is False
        assert "exclude_keyword" in reason

    def test_required_keywords_any_no_match_rejected(self, tmp_path):
        """required_keywords_any set but none present in text → rejected."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(
            filters_file,
            {"required_keywords_any": ["product manager", "pm", "product owner"]},
        )

        passes, reason = should_score_advanced(
            vacancy_text="Разработчик Python в стартап",
            salary_min=None,
            salary_currency="",
            has_salary=False,
            filters_path=str(filters_file),
        )
        assert passes is False
        assert "required_keywords_any" in reason

    def test_required_keywords_any_match_passes(self, tmp_path):
        """At least one required_keywords_any found in text → passes."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(
            filters_file,
            {"required_keywords_any": ["product manager", "pm", "product owner"]},
        )

        passes, reason = should_score_advanced(
            vacancy_text="Senior Product Manager в Яндекс",
            salary_min=None,
            salary_currency="",
            has_salary=False,
            filters_path=str(filters_file),
        )
        assert passes is True
        assert reason == ""

    def test_non_rur_currency_skips_salary_floor(self, tmp_path):
        """Non-RUR salary is not checked against the floor (conservative pass)."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(filters_file, {"min_salary_rub": 200_000, "allow_no_salary": False})

        # USD salary below the RUB floor — should pass (can't compare currencies)
        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=1_000,
            salary_currency="USD",
            has_salary=True,
            filters_path=str(filters_file),
        )
        assert passes is True
        assert reason == ""

    def test_salary_only_to_no_from_passes_floor(self, tmp_path):
        """salary_min=None (only salary.to provided) → floor check skipped (conservative)."""
        from capabilities.career_os.skills.vacancy_ingest_hh.filters import (
            should_score_advanced,
        )
        filters_file = tmp_path / "hh_filters.json"
        _write_filters(filters_file, {"min_salary_rub": 200_000, "allow_no_salary": True})

        passes, reason = should_score_advanced(
            vacancy_text="PM role",
            salary_min=None,   # only salary.to was provided
            salary_currency="RUR",
            has_salary=True,   # salary dict exists
            filters_path=str(filters_file),
        )
        assert passes is True
        assert reason == ""
