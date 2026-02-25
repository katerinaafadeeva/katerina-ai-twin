"""Tests for capabilities/career_os/skills/cover_letter/store.py.

Covers:
- save_cover_letter: creates new record, idempotent on duplicate, returns rowid
- get_cover_letter_for_action: None for missing, dict for existing
- get_cover_letter_for_job: most recent, None for missing
- get_today_cover_letter_count: 0 on empty, excludes fallbacks, counts only today
- was_cover_letter_cap_notification_sent_today: False initially, True after event
"""

import sqlite3

import pytest

from capabilities.career_os.skills.cover_letter.store import (
    get_cover_letter_for_action,
    get_cover_letter_for_job,
    get_today_cover_letter_count,
    save_cover_letter,
    was_cover_letter_cap_notification_sent_today,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_job_raw(conn: sqlite3.Connection, hh_id: str = "hh001") -> int:
    cursor = conn.execute(
        "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES ('text', 'hh', ?)",
        (f"hh_{hh_id}",),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_action(conn: sqlite3.Connection, job_raw_id: int) -> int:
    cursor = conn.execute(
        "INSERT INTO actions (job_raw_id, action_type, status) VALUES (?, 'AUTO_APPLY', 'pending')",
        (job_raw_id,),
    )
    conn.commit()
    return cursor.lastrowid


def _save_cl(
    conn: sqlite3.Connection,
    job_raw_id: int,
    action_id: int,
    is_fallback: bool = False,
    text: str = "Добрый день! Это тестовое сопроводительное письмо для позиции.",
) -> int:
    rowid = save_cover_letter(
        conn,
        job_raw_id=job_raw_id,
        action_id=action_id,
        letter_text=text,
        model="claude-haiku-4-5-20251001" if not is_fallback else "fallback",
        prompt_version="cover_letter_v1",
        is_fallback=is_fallback,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.001,
    )
    conn.commit()
    return rowid


# ---------------------------------------------------------------------------
# save_cover_letter
# ---------------------------------------------------------------------------


class TestSaveCoverLetter:
    def test_creates_new_record_returns_rowid(self, db_conn):
        job_id = _insert_job_raw(db_conn)
        action_id = _insert_action(db_conn, job_id)
        rowid = _save_cl(db_conn, job_id, action_id)
        assert rowid > 0

    def test_idempotent_on_duplicate_returns_zero(self, db_conn):
        job_id = _insert_job_raw(db_conn)
        action_id = _insert_action(db_conn, job_id)
        rowid1 = _save_cl(db_conn, job_id, action_id)
        rowid2 = _save_cl(db_conn, job_id, action_id)
        assert rowid1 > 0
        assert rowid2 == 0  # INSERT OR IGNORE → 0 on duplicate

    def test_sets_is_fallback_false(self, db_conn):
        job_id = _insert_job_raw(db_conn)
        action_id = _insert_action(db_conn, job_id)
        rowid = _save_cl(db_conn, job_id, action_id, is_fallback=False)
        row = db_conn.execute("SELECT is_fallback FROM cover_letters WHERE id = ?", (rowid,)).fetchone()
        assert row["is_fallback"] == 0

    def test_sets_is_fallback_true(self, db_conn):
        job_id = _insert_job_raw(db_conn)
        action_id = _insert_action(db_conn, job_id)
        rowid = _save_cl(db_conn, job_id, action_id, is_fallback=True)
        row = db_conn.execute("SELECT is_fallback FROM cover_letters WHERE id = ?", (rowid,)).fetchone()
        assert row["is_fallback"] == 1

    def test_stores_tokens_and_cost(self, db_conn):
        job_id = _insert_job_raw(db_conn)
        action_id = _insert_action(db_conn, job_id)
        rowid = save_cover_letter(
            db_conn,
            job_raw_id=job_id,
            action_id=action_id,
            letter_text="Тест письма для проверки токенов и стоимости вызова LLM.",
            model="claude-haiku-4-5-20251001",
            prompt_version="cover_letter_v1",
            is_fallback=False,
            input_tokens=150,
            output_tokens=300,
            cost_usd=0.00195,
        )
        db_conn.commit()
        row = db_conn.execute("SELECT * FROM cover_letters WHERE id = ?", (rowid,)).fetchone()
        assert row["input_tokens"] == 150
        assert row["output_tokens"] == 300
        assert abs(row["cost_usd"] - 0.00195) < 1e-6


# ---------------------------------------------------------------------------
# get_cover_letter_for_action
# ---------------------------------------------------------------------------


class TestGetCoverLetterForAction:
    def test_returns_none_for_missing_action(self, db_conn):
        result = get_cover_letter_for_action(db_conn, action_id=99999)
        assert result is None

    def test_returns_dict_for_existing(self, db_conn):
        job_id = _insert_job_raw(db_conn, "hh002")
        action_id = _insert_action(db_conn, job_id)
        _save_cl(db_conn, job_id, action_id)
        result = get_cover_letter_for_action(db_conn, action_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["action_id"] == action_id
        assert result["job_raw_id"] == job_id

    def test_returns_letter_text(self, db_conn):
        job_id = _insert_job_raw(db_conn, "hh003")
        action_id = _insert_action(db_conn, job_id)
        _save_cl(db_conn, job_id, action_id, text="Уникальное письмо для проверки текста.")
        result = get_cover_letter_for_action(db_conn, action_id)
        assert "Уникальное письмо" in result["letter_text"]


# ---------------------------------------------------------------------------
# get_cover_letter_for_job
# ---------------------------------------------------------------------------


class TestGetCoverLetterForJob:
    def test_returns_none_for_missing_job(self, db_conn):
        result = get_cover_letter_for_job(db_conn, job_raw_id=99999)
        assert result is None

    def test_returns_most_recent_for_job(self, db_conn):
        """If multiple letters for same job_raw_id, return most recent."""
        job_id = _insert_job_raw(db_conn, "hh004")
        action_id_1 = _insert_action(db_conn, job_id)
        action_id_2 = _insert_action(db_conn, job_id)
        # Insert first letter with an explicit old timestamp to avoid same-second ties
        db_conn.execute(
            """INSERT INTO cover_letters
               (job_raw_id, action_id, letter_text, model, prompt_version, created_at)
               VALUES (?, ?, 'Первое письмо', 'fallback', 'cover_letter_v1', '2020-01-01 00:00:00')""",
            (job_id, action_id_1),
        )
        db_conn.commit()
        _save_cl(db_conn, job_id, action_id_2, text="Второе письмо — более новое")
        result = get_cover_letter_for_job(db_conn, job_id)
        assert "Второе письмо" in result["letter_text"]


# ---------------------------------------------------------------------------
# get_today_cover_letter_count
# ---------------------------------------------------------------------------


class TestGetTodayCoverLetterCount:
    def test_returns_0_on_empty_db(self, db_conn):
        assert get_today_cover_letter_count(db_conn) == 0

    def test_counts_non_fallback_only(self, db_conn):
        """Fallback letters do not count toward the daily cap."""
        job_id = _insert_job_raw(db_conn, "hh005")
        action_id_llm = _insert_action(db_conn, job_id)
        job_id_fb = _insert_job_raw(db_conn, "hh006")
        action_id_fb = _insert_action(db_conn, job_id_fb)
        _save_cl(db_conn, job_id, action_id_llm, is_fallback=False)
        _save_cl(db_conn, job_id_fb, action_id_fb, is_fallback=True)
        assert get_today_cover_letter_count(db_conn) == 1

    def test_counts_all_llm_letters_today(self, db_conn):
        for i in range(3):
            job_id = _insert_job_raw(db_conn, f"hh_cap_{i}")
            action_id = _insert_action(db_conn, job_id)
            _save_cl(db_conn, job_id, action_id, is_fallback=False)
        assert get_today_cover_letter_count(db_conn) == 3


# ---------------------------------------------------------------------------
# was_cover_letter_cap_notification_sent_today
# ---------------------------------------------------------------------------


class TestCapNotificationSent:
    def test_returns_false_initially(self, db_conn):
        assert was_cover_letter_cap_notification_sent_today(db_conn) is False

    def test_returns_true_after_event(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('cover_letter.cap_reached', '{}', 'test')"
        )
        db_conn.commit()
        assert was_cover_letter_cap_notification_sent_today(db_conn) is True

    def test_different_event_does_not_trigger(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES ('scoring.cap_reached', '{}', 'test')"
        )
        db_conn.commit()
        assert was_cover_letter_cap_notification_sent_today(db_conn) is False
