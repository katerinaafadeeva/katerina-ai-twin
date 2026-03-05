"""Tests for ISSUE-3 (/letter command) and ISSUE-4 (progress bars, /queue command).

Covers:
- _pbar: progress bar helper function
- get_cover_letter_for_action: used by /letter command
- /queue: returns pending tasks correctly
"""

import pytest

from capabilities.career_os.skills.control_plane.handlers import _pbar


# ---------------------------------------------------------------------------
# _pbar — pure function tests
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_empty_bar(self):
        """0/10 → all empty."""
        assert _pbar(0, 10) == "░░░░░░░░░░"

    def test_full_bar(self):
        """10/10 → all filled."""
        assert _pbar(10, 10) == "██████████"

    def test_half_bar(self):
        """5/10 → half filled."""
        assert _pbar(5, 10) == "█████░░░░░"

    def test_zero_total_no_division_error(self):
        """0/0 → no ZeroDivisionError, returns empty bar."""
        result = _pbar(0, 0)
        assert result == "░░░░░░░░░░"

    def test_over_cap_clamps_to_full(self):
        """current > total → full bar (no index error)."""
        result = _pbar(15, 10)
        assert result == "██████████"

    def test_width_param(self):
        """Custom width is respected."""
        result = _pbar(2, 4, width=4)
        assert result == "██░░"

    def test_one_third(self):
        """~3/10 → 3 filled (rounded)."""
        result = _pbar(3, 10)
        assert len(result) == 10
        assert result.count("█") == 3

    def test_bar_length_always_equals_width(self):
        """Bar length always equals width regardless of values."""
        for current in range(0, 12):
            bar = _pbar(current, 10, width=8)
            assert len(bar) == 8


# ---------------------------------------------------------------------------
# get_cover_letter_for_action — used by /letter command
# ---------------------------------------------------------------------------


class TestGetCoverLetterForAction:
    def _insert_cover_letter(self, conn, action_id: int, letter_text: str) -> None:
        """Insert a cover letter row for testing."""
        conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (?, 'text', 'hh', ?)",
            (action_id, f"hh_{action_id}"),
        )
        conn.execute(
            "INSERT INTO actions (id, job_raw_id, action_type, status) VALUES (?, ?, 'AUTO_APPLY', 'pending')",
            (action_id, action_id),
        )
        conn.execute(
            "INSERT INTO cover_letters "
            "(job_raw_id, action_id, letter_text, model, prompt_version, is_fallback) "
            "VALUES (?, ?, ?, 'test', 'v1', 0)",
            (action_id, action_id, letter_text),
        )
        conn.commit()

    def test_returns_letter_for_existing_action(self, db_conn):
        """Returns letter dict when action has a cover letter."""
        from capabilities.career_os.skills.cover_letter.store import get_cover_letter_for_action

        self._insert_cover_letter(db_conn, 1, "Добрый день, меня интересует эта вакансия.")
        result = get_cover_letter_for_action(db_conn, 1)

        assert result is not None
        assert result["letter_text"] == "Добрый день, меня интересует эта вакансия."

    def test_returns_none_for_missing_action(self, db_conn):
        """Returns None when action_id doesn't exist."""
        from capabilities.career_os.skills.cover_letter.store import get_cover_letter_for_action

        result = get_cover_letter_for_action(db_conn, 9999)
        assert result is None


# ---------------------------------------------------------------------------
# /queue — pending tasks display
# ---------------------------------------------------------------------------


class TestQueueCommand:
    def _insert_auto_apply_action(self, conn, action_id: int, hh_vacancy_id: str = "123") -> None:
        """Insert job_raw and AUTO_APPLY action for /queue test."""
        conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id, hh_vacancy_id) "
            "VALUES (?, 'Python разработчик в Яндекс', 'hh', ?, ?)",
            (action_id, f"hh_{hh_vacancy_id}", hh_vacancy_id),
        )
        conn.execute(
            "INSERT INTO actions (id, job_raw_id, action_type, status, score) "
            "VALUES (?, ?, 'AUTO_APPLY', 'pending', 7)",
            (action_id, action_id),
        )
        conn.commit()

    def test_get_pending_apply_tasks_returns_pending(self, db_conn):
        """get_pending_apply_tasks returns actions with hh_vacancy_id and no successful run."""
        from capabilities.career_os.skills.hh_apply.store import get_pending_apply_tasks

        self._insert_auto_apply_action(db_conn, 1, "111")
        self._insert_auto_apply_action(db_conn, 2, "222")

        tasks = get_pending_apply_tasks(db_conn, limit=10)
        assert len(tasks) == 2
        action_ids = [t["action_id"] for t in tasks]
        assert 1 in action_ids
        assert 2 in action_ids

    def test_get_pending_apply_tasks_excludes_done(self, db_conn):
        """Tasks with a successful apply_run are excluded from the queue."""
        from capabilities.career_os.skills.hh_apply.store import get_pending_apply_tasks

        self._insert_auto_apply_action(db_conn, 3, "333")
        # Insert a successful apply_run → should exclude this task
        db_conn.execute(
            "INSERT INTO apply_runs (action_id, attempt, status, finished_at) VALUES (3, 1, 'done', datetime('now'))"
        )
        db_conn.commit()

        tasks = get_pending_apply_tasks(db_conn, limit=10)
        action_ids = [t["action_id"] for t in tasks]
        assert 3 not in action_ids

    def test_get_pending_apply_tasks_respects_limit(self, db_conn):
        """Limit parameter restricts number of returned tasks."""
        from capabilities.career_os.skills.hh_apply.store import get_pending_apply_tasks

        for i in range(5):
            self._insert_auto_apply_action(db_conn, 10 + i, f"hh_id_{i}")

        tasks = get_pending_apply_tasks(db_conn, limit=2)
        assert len(tasks) == 2
