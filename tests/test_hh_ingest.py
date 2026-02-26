"""Tests for vacancy_ingest_hh store, handler, and scoring cap.

Covers:
- normalize_vacancy: field extraction, HTML stripping
- load_search_queries: valid file, missing file, invalid JSON, bad format
- store: is_hh_vacancy_ingested, is_canonical_key_ingested, save_hh_vacancy,
         get_today_scored_count, was_scoring_cap_notification_sent_today
- compute_canonical_key: determinism, cross-source dedup
- ingest_hh_vacancies: dedup, pre-filter, new vacancy saved
- scoring cap functions
"""

import json
import sqlite3
from pathlib import Path

import pytest

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.handler import (
    ingest_hh_vacancies,
    load_search_queries,
    normalize_vacancy,
)
from capabilities.career_os.skills.vacancy_ingest_hh.store import (
    compute_canonical_key,
    get_today_scored_count,
    is_canonical_key_ingested,
    is_hh_vacancy_ingested,
    save_hh_vacancy,
    was_scoring_cap_notification_sent_today,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    negative_signals: tuple = ("MLM",),
    industries_excluded: tuple = ("gambling",),
) -> Profile:
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


def _make_hh_item(
    id: str = "123",
    name: str = "Product Manager",
    employer: str = "Tech Corp",
    requirement: str = "Python, SQL",
    responsibility: str = "Управление продуктом",
) -> dict:
    return {
        "id": id,
        "name": name,
        "employer": {"name": employer},
        "snippet": {
            "requirement": requirement,
            "responsibility": responsibility,
        },
        "salary": {"from": 200000, "to": 350000, "currency": "RUB"},
        "area": {"name": "Москва"},
        "schedule": {"name": "Удалённая работа"},
        "alternate_url": f"https://hh.ru/vacancy/{id}",
    }


def _insert_job_score(conn: sqlite3.Connection, job_raw_id: int) -> None:
    """Insert a job_scores row for today to simulate a scored vacancy."""
    conn.execute(
        """
        INSERT INTO job_scores
            (job_raw_id, score, reasons_json, explanation, model, prompt_version, profile_hash)
        VALUES (?, 7, '[]', 'test', 'test-model', 'v1', 'hash1')
        """,
        (job_raw_id,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# normalize_vacancy
# ---------------------------------------------------------------------------


class TestNormalizeVacancy:
    def test_extracts_hh_vacancy_id(self):
        item = _make_hh_item(id="999")
        result = normalize_vacancy(item)
        assert result["hh_vacancy_id"] == "999"

    def test_extracts_source_url(self):
        item = _make_hh_item(id="777")
        result = normalize_vacancy(item)
        assert "hh.ru/vacancy/777" in result["source_url"]

    def test_raw_text_contains_position(self):
        item = _make_hh_item(name="Chief PM")
        result = normalize_vacancy(item)
        assert "Chief PM" in result["raw_text"]

    def test_raw_text_contains_employer(self):
        item = _make_hh_item(employer="Яндекс")
        result = normalize_vacancy(item)
        assert "Яндекс" in result["raw_text"]

    def test_raw_text_contains_salary(self):
        item = _make_hh_item()
        result = normalize_vacancy(item)
        assert "200000" in result["raw_text"] or "от 200000" in result["raw_text"]

    def test_strips_html_from_snippet(self):
        item = _make_hh_item(requirement="<highlighttext>Python</highlighttext> и SQL")
        result = normalize_vacancy(item)
        assert "<highlighttext>" not in result["raw_text"]
        assert "Python" in result["raw_text"]

    def test_missing_employer_handled(self):
        item = _make_hh_item()
        item["employer"] = None
        result = normalize_vacancy(item)
        assert result["hh_vacancy_id"] == item["id"]

    def test_missing_id_returns_empty_string(self):
        item = _make_hh_item()
        del item["id"]
        result = normalize_vacancy(item)
        assert result["hh_vacancy_id"] == ""

    def test_none_snippet_fields_handled(self):
        item = _make_hh_item()
        item["snippet"] = {"requirement": None, "responsibility": None}
        result = normalize_vacancy(item)
        assert isinstance(result["raw_text"], str)


# ---------------------------------------------------------------------------
# load_search_queries
# ---------------------------------------------------------------------------


class TestLoadSearchQueries:
    def test_loads_valid_file(self, tmp_path):
        f = tmp_path / "searches.json"
        f.write_text(json.dumps([{"text": "Product Manager", "area": "1"}]))
        queries = load_search_queries(str(f))
        assert len(queries) == 1
        assert queries[0]["text"] == "Product Manager"

    def test_missing_file_returns_empty(self, tmp_path):
        queries = load_search_queries(str(tmp_path / "nonexistent.json"))
        assert queries == []

    def test_invalid_json_returns_empty(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        queries = load_search_queries(str(f))
        assert queries == []

    def test_non_array_returns_empty(self, tmp_path):
        f = tmp_path / "searches.json"
        f.write_text(json.dumps({"searches": []}))
        queries = load_search_queries(str(f))
        assert queries == []

    def test_filters_out_items_without_text(self, tmp_path):
        f = tmp_path / "searches.json"
        f.write_text(json.dumps([
            {"text": "PM", "area": "1"},
            {"area": "2"},  # missing "text"
            {"text": ""},   # empty "text" is falsy
        ]))
        queries = load_search_queries(str(f))
        assert len(queries) == 1
        assert queries[0]["text"] == "PM"


# ---------------------------------------------------------------------------
# compute_canonical_key
# ---------------------------------------------------------------------------


class TestComputeCanonicalKey:
    def test_deterministic(self):
        text = "Позиция: Product Manager"
        assert compute_canonical_key(text) == compute_canonical_key(text)

    def test_case_insensitive(self):
        assert compute_canonical_key("Hello World") == compute_canonical_key("hello world")

    def test_strips_whitespace(self):
        assert compute_canonical_key("  hello  ") == compute_canonical_key("hello")

    def test_different_texts_different_keys(self):
        k1 = compute_canonical_key("Product Manager at Google")
        k2 = compute_canonical_key("Software Engineer at Google")
        assert k1 != k2

    def test_returns_16_char_hex(self):
        key = compute_canonical_key("any text")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# store: is_hh_vacancy_ingested, is_canonical_key_ingested
# ---------------------------------------------------------------------------


class TestDedup:
    def test_is_hh_vacancy_ingested_returns_false_for_new(self, db_conn):
        assert is_hh_vacancy_ingested(db_conn, "hh_99999") is False

    def test_is_hh_vacancy_ingested_returns_true_after_save(self, db_conn):
        save_hh_vacancy(db_conn, "hh_42", "some text", "https://hh.ru/42")
        db_conn.commit()
        assert is_hh_vacancy_ingested(db_conn, "hh_42") is True

    def test_is_canonical_key_ingested_returns_false_for_new(self, db_conn):
        key = compute_canonical_key("totally new vacancy text")
        assert is_canonical_key_ingested(db_conn, key) is False

    def test_is_canonical_key_ingested_returns_true_after_save(self, db_conn):
        text = "Позиция: Senior PM at BigCorp"
        save_hh_vacancy(db_conn, "hh_777", text, "")
        db_conn.commit()
        key = compute_canonical_key(text)
        assert is_canonical_key_ingested(db_conn, key) is True

    def test_canonical_key_catches_cross_source_duplicate(self, db_conn):
        """Same text from TG source → canonical_key matches HH vacancy."""
        text = "Позиция: Product Manager\nКомпания: Яндекс"
        # Simulate TG ingest of the same text
        key = compute_canonical_key(text)
        db_conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id, canonical_key) VALUES (?, 'tg', 'tg_123', ?)",
            (text, key),
        )
        db_conn.commit()
        # Now HH would find the same canonical_key
        assert is_canonical_key_ingested(db_conn, key) is True


# ---------------------------------------------------------------------------
# save_hh_vacancy
# ---------------------------------------------------------------------------


class TestSaveHhVacancy:
    def test_creates_new_record_returns_is_new_true(self, db_conn):
        job_id, is_new = save_hh_vacancy(db_conn, "hh_1", "text", "url")
        db_conn.commit()
        assert is_new is True
        assert job_id > 0

    def test_returns_existing_id_on_duplicate(self, db_conn):
        job_id_1, _ = save_hh_vacancy(db_conn, "hh_2", "text", "url")
        db_conn.commit()
        job_id_2, is_new = save_hh_vacancy(db_conn, "hh_2", "text", "url")
        assert is_new is False
        assert job_id_1 == job_id_2

    def test_sets_source_to_hh(self, db_conn):
        job_id, _ = save_hh_vacancy(db_conn, "hh_3", "vacancy text", "")
        db_conn.commit()
        row = db_conn.execute("SELECT source FROM job_raw WHERE id = ?", (job_id,)).fetchone()
        assert row["source"] == "hh"

    def test_sets_hh_vacancy_id_column(self, db_conn):
        job_id, _ = save_hh_vacancy(db_conn, "hh_555", "text", "")
        db_conn.commit()
        row = db_conn.execute("SELECT hh_vacancy_id FROM job_raw WHERE id = ?", (job_id,)).fetchone()
        assert row["hh_vacancy_id"] == "hh_555"

    def test_source_message_id_format(self, db_conn):
        job_id, _ = save_hh_vacancy(db_conn, "hh_888", "text", "")
        db_conn.commit()
        row = db_conn.execute("SELECT source_message_id FROM job_raw WHERE id = ?", (job_id,)).fetchone()
        assert row["source_message_id"] == "hh_hh_888"

    def test_canonical_key_populated(self, db_conn):
        text = "Позиция: PM"
        job_id, _ = save_hh_vacancy(db_conn, "hh_10", text, "")
        db_conn.commit()
        row = db_conn.execute("SELECT canonical_key FROM job_raw WHERE id = ?", (job_id,)).fetchone()
        assert row["canonical_key"] == compute_canonical_key(text)


# ---------------------------------------------------------------------------
# ingest_hh_vacancies (integration)
# ---------------------------------------------------------------------------


class TestIngestHhVacancies:
    def test_new_vacancy_returns_new_count_1(self, db_conn, monkeypatch):
        """End-to-end: one new clean vacancy → new=1."""
        # Patch get_conn to return our test db_conn
        import capabilities.career_os.skills.vacancy_ingest_hh.handler as handler_module
        monkeypatch.setattr(handler_module, "get_conn", lambda: db_conn)
        # Also patch emit to avoid actual DB writes from events
        monkeypatch.setattr(handler_module, "emit", lambda *a, **kw: None)
        # Disable advanced filter (not under test here — dedup logic is)
        monkeypatch.setattr(handler_module, "should_score_advanced", lambda *a, **kw: (True, ""))

        profile = _make_profile(negative_signals=(), industries_excluded=())
        items = [_make_hh_item(id="111")]
        counts = ingest_hh_vacancies(items, profile)
        assert counts["new"] == 1
        assert counts["duplicate"] == 0
        assert counts["filtered"] == 0
        assert counts["total"] == 1

    def test_duplicate_hh_id_not_counted_twice(self, db_conn, monkeypatch):
        import capabilities.career_os.skills.vacancy_ingest_hh.handler as handler_module
        monkeypatch.setattr(handler_module, "get_conn", lambda: db_conn)
        monkeypatch.setattr(handler_module, "emit", lambda *a, **kw: None)
        # Disable advanced filter (not under test here — dedup logic is)
        monkeypatch.setattr(handler_module, "should_score_advanced", lambda *a, **kw: (True, ""))

        profile = _make_profile(negative_signals=(), industries_excluded=())
        items = [_make_hh_item(id="222"), _make_hh_item(id="222")]
        counts = ingest_hh_vacancies(items, profile)
        assert counts["new"] == 1
        assert counts["duplicate"] == 1

    def test_pre_filtered_vacancy_counted_filtered(self, db_conn, monkeypatch):
        import capabilities.career_os.skills.vacancy_ingest_hh.handler as handler_module
        monkeypatch.setattr(handler_module, "get_conn", lambda: db_conn)
        monkeypatch.setattr(handler_module, "emit", lambda *a, **kw: None)

        profile = _make_profile(negative_signals=("MLM",), industries_excluded=())
        items = [_make_hh_item(id="333", name="MLM менеджер")]
        counts = ingest_hh_vacancies(items, profile)
        assert counts["filtered"] == 1
        assert counts["new"] == 0

    def test_pre_filtered_vacancy_not_saved_to_db(self, db_conn, monkeypatch):
        """Pre-filtered vacancies must NOT appear in job_raw."""
        import capabilities.career_os.skills.vacancy_ingest_hh.handler as handler_module
        monkeypatch.setattr(handler_module, "get_conn", lambda: db_conn)
        monkeypatch.setattr(handler_module, "emit", lambda *a, **kw: None)

        profile = _make_profile(negative_signals=("gambling",), industries_excluded=())
        items = [_make_hh_item(id="444", name="PM gambling платформа")]
        ingest_hh_vacancies(items, profile)

        row = db_conn.execute(
            "SELECT * FROM job_raw WHERE hh_vacancy_id = 'hh_444'"
        ).fetchone()
        assert row is None  # must NOT be saved

    def test_missing_id_skipped_gracefully(self, db_conn, monkeypatch):
        import capabilities.career_os.skills.vacancy_ingest_hh.handler as handler_module
        monkeypatch.setattr(handler_module, "get_conn", lambda: db_conn)
        monkeypatch.setattr(handler_module, "emit", lambda *a, **kw: None)

        profile = _make_profile(negative_signals=(), industries_excluded=())
        item = _make_hh_item()
        del item["id"]
        counts = ingest_hh_vacancies([item], profile)
        assert counts["total"] == 1
        assert counts["new"] == 0  # skipped


# ---------------------------------------------------------------------------
# Scoring cap functions
# ---------------------------------------------------------------------------


class TestScoringCap:
    def test_get_today_scored_count_returns_0_on_empty(self, db_conn):
        assert get_today_scored_count(db_conn) == 0

    def test_get_today_scored_count_counts_today_only(self, db_conn):
        # Insert job_raw and job_score for today
        cursor = db_conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES ('t', 'hh', 'hh_sc1')"
        )
        job_id = cursor.lastrowid
        _insert_job_score(db_conn, job_id)
        assert get_today_scored_count(db_conn) == 1

    def test_was_scoring_cap_notification_sent_today_returns_false_initially(self, db_conn):
        assert was_scoring_cap_notification_sent_today(db_conn) is False

    def test_was_scoring_cap_notification_sent_today_returns_true_after_event(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('scoring.cap_reached', '{}', 'test')"
        )
        db_conn.commit()
        assert was_scoring_cap_notification_sent_today(db_conn) is True

    def test_different_event_name_does_not_trigger_cap_check(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('other.event', '{}', 'test')"
        )
        db_conn.commit()
        assert was_scoring_cap_notification_sent_today(db_conn) is False
