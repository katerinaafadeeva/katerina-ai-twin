"""Tests for capabilities/career_os/skills/control_plane/formatters.py.

Covers:
- extract_vacancy_title: parses "Позиция:" and "Компания:" lines
- extract_vacancy_title: handles missing fields gracefully
- extract_vacancy_title: truncates long position/company names
- extract_vacancy_title: fallback to first 250 chars when no structured fields
- extract_vacancy_title: empty string input handled safely
"""

import pytest

from capabilities.career_os.skills.control_plane.formatters import extract_vacancy_title


class TestExtractVacancyTitle:
    def test_parses_position_and_company(self):
        raw = "Позиция: Product Manager\nКомпания: Яндекс\nОпыт: 3+ лет"
        title, company = extract_vacancy_title(raw)
        assert title == "Product Manager"
        assert company == "Яндекс"

    def test_parses_position_only(self):
        raw = "Позиция: Data Analyst\nОпыт от 2 лет"
        title, company = extract_vacancy_title(raw)
        assert title == "Data Analyst"
        assert company == ""

    def test_parses_company_only_falls_back_to_text(self):
        """No 'Позиция:' → fallback to first 250 chars of raw_text."""
        raw = "Компания: Сбер\nТребуется специалист с опытом"
        title, company = extract_vacancy_title(raw)
        # title falls back to first 250 chars since no "Позиция:" line
        assert "Компания" in title or "Сбер" in title or "Требуется" in title
        assert company == "Сбер"

    def test_fallback_to_first_250_chars_when_no_fields(self):
        """No 'Позиция:' or 'Компания:' → position = first 250 chars of text."""
        raw = "Senior PM needed. " * 30  # >250 chars
        title, company = extract_vacancy_title(raw)
        assert len(title) <= 250
        assert "Senior PM" in title
        assert company == ""

    def test_empty_string_returns_defaults(self):
        title, company = extract_vacancy_title("")
        assert title == "Вакансия"
        assert company == ""

    def test_truncates_long_position_to_60_chars(self):
        long_title = "A" * 100
        raw = f"Позиция: {long_title}\nКомпания: Test"
        title, company = extract_vacancy_title(raw)
        assert len(title) <= 60

    def test_truncates_long_company_to_40_chars(self):
        long_company = "B" * 80
        raw = f"Позиция: PM\nКомпания: {long_company}"
        title, company = extract_vacancy_title(raw)
        assert len(company) <= 40

    def test_handles_extra_whitespace(self):
        raw = "Позиция:   Product Owner   \nКомпания:   VK   "
        title, company = extract_vacancy_title(raw)
        assert title == "Product Owner"
        assert company == "VK"

    def test_order_insensitive(self):
        """Company before Позиция still parsed correctly."""
        raw = "Компания: Mail.ru\nПозиция: Backend Engineer"
        title, company = extract_vacancy_title(raw)
        assert title == "Backend Engineer"
        assert company == "Mail.ru"


class TestExtractVacancyTitleInTodaySummary:
    """Integration: get_today_summary includes applies_done and apply_daily_cap."""

    def test_summary_includes_applies_done_key(self, db_conn):
        from capabilities.career_os.skills.control_plane.store import get_today_summary
        s = get_today_summary(db_conn, apply_daily_cap=10)
        assert "applies_done" in s
        assert "apply_daily_cap" in s

    def test_applies_done_zero_when_no_runs(self, db_conn):
        from capabilities.career_os.skills.control_plane.store import get_today_summary
        s = get_today_summary(db_conn, apply_daily_cap=10)
        assert s["applies_done"] == 0

    def test_applies_done_counts_done_runs_only(self, db_conn):
        from capabilities.career_os.skills.control_plane.store import get_today_summary

        # Insert a job_raw and action first (for FK)
        db_conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES ('vac', 'hh', 'hh-1')"
        )
        job_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute(
            "INSERT INTO actions (job_raw_id, action_type, status, score, reason, actor) "
            "VALUES (?, 'AUTO_APPLY', 'pending', 6, 'test', 'test')",
            (job_id,),
        )
        action_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.commit()

        # Insert done apply_run
        db_conn.execute(
            "INSERT INTO apply_runs (action_id, attempt, status, finished_at) "
            "VALUES (?, 1, 'done', datetime('now'))",
            (action_id,),
        )
        # Insert failed apply_run — should NOT be counted
        db_conn.execute(
            "INSERT INTO apply_runs (action_id, attempt, status, finished_at) "
            "VALUES (?, 2, 'failed', datetime('now'))",
            (action_id,),
        )
        db_conn.commit()

        s = get_today_summary(db_conn, apply_daily_cap=5)
        assert s["applies_done"] == 1  # only 'done' counts
        assert s["apply_daily_cap"] == 5

    def test_apply_daily_cap_passed_through(self, db_conn):
        from capabilities.career_os.skills.control_plane.store import get_today_summary
        s = get_today_summary(db_conn, apply_daily_cap=42)
        assert s["apply_daily_cap"] == 42
