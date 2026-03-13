"""Tests for ISSUE-1: independent HH and TG scoring daily caps.

Covers:
- get_today_scored_count_by_source: counts vacancies per source
- was_tg_scoring_cap_notification_sent_today: reads events table
- TG vacancy scored when HH cap exhausted (uses continue, not break)
- HH vacancy skipped when HH cap exhausted
- TG vacancy skipped when TG cap exhausted
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.career_os.skills.vacancy_ingest_hh.store import (
    get_today_scored_count_by_source,
    was_tg_scoring_cap_notification_sent_today,
)

_W = "capabilities.career_os.skills.match_scoring.worker"


# ---------------------------------------------------------------------------
# get_today_scored_count_by_source — store tests
# ---------------------------------------------------------------------------


class TestGetTodayScoredCountBySource:
    def _insert_job_and_score(self, conn, source: str, uid: str) -> None:
        cur = conn.execute(
            "INSERT INTO job_raw (raw_text, source, source_message_id) VALUES (?, ?, ?)",
            (f"text {uid}", source, uid),
        )
        conn.commit()
        conn.execute(
            "INSERT INTO job_scores "
            "(job_raw_id, score, reasons_json, explanation, model, prompt_version, profile_hash, scorer_version) "
            "VALUES (?, 7, '[]', 'ok', 'test', 'v1', 'hash1', 'v1')",
            (cur.lastrowid,),
        )
        conn.commit()

    def test_counts_hh_only(self, db_conn):
        self._insert_job_and_score(db_conn, "hh", "hh_1")
        self._insert_job_and_score(db_conn, "telegram_forward", "tg_1")
        assert get_today_scored_count_by_source(db_conn, "hh") == 1
        assert get_today_scored_count_by_source(db_conn, "telegram_forward") == 1

    def test_counts_multiple_hh(self, db_conn):
        self._insert_job_and_score(db_conn, "hh", "hh_1")
        self._insert_job_and_score(db_conn, "hh", "hh_2")
        assert get_today_scored_count_by_source(db_conn, "hh") == 2
        assert get_today_scored_count_by_source(db_conn, "telegram_forward") == 0

    def test_returns_zero_for_unknown_source(self, db_conn):
        assert get_today_scored_count_by_source(db_conn, "unknown") == 0

    def test_returns_zero_when_empty(self, db_conn):
        assert get_today_scored_count_by_source(db_conn, "hh") == 0


class TestWasTgScoringCapNotificationSentToday:
    def test_false_when_no_event(self, db_conn):
        assert was_tg_scoring_cap_notification_sent_today(db_conn) is False

    def test_true_after_tg_cap_event(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES (?, '{}', 'test')",
            ("scoring.tg_cap_reached",),
        )
        db_conn.commit()
        assert was_tg_scoring_cap_notification_sent_today(db_conn) is True

    def test_ignores_hh_cap_event(self, db_conn):
        db_conn.execute(
            "INSERT INTO events (event_name, payload_json, actor) VALUES (?, '{}', 'test')",
            ("scoring.cap_reached",),
        )
        db_conn.commit()
        assert was_tg_scoring_cap_notification_sent_today(db_conn) is False


# ---------------------------------------------------------------------------
# scoring_worker cap logic — mock-based tests via ExitStack
# ---------------------------------------------------------------------------


def _make_cfg(hh_cap=40, tg_cap=20):
    cfg = MagicMock()
    cfg.hh_scoring_daily_cap = hh_cap
    cfg.tg_scoring_daily_cap = tg_cap
    cfg.cover_letter_daily_cap = 0
    cfg.allowed_telegram_ids = [12345]
    cfg.profile_path = "identity/profile.json"
    cfg.resume_path = "identity/resume.md"
    cfg.scoring_worker_interval = 999
    return cfg


def _make_vacancy(job_raw_id, source):
    return {"id": job_raw_id, "raw_text": "Ищем разработчика.", "source": source,
            "hh_vacancy_id": f"hh{job_raw_id}" if source == "hh" else None}


async def _run_worker_once(mock_bot, cfg, vacancies, count_by_source_fn):
    """Run one scoring_worker iteration with given config/vacancies/cap mock."""
    scored_ids = []

    async def mock_score(vacancy_text, vacancy_id, profile, correlation_id):
        scored_ids.append(vacancy_id)
        r = MagicMock()
        r.score = 6
        r.reasons = []
        r.explanation = "ok"
        return r

    mock_gc = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)

    mock_profile = MagicMock()
    mock_profile.from_file.return_value = MagicMock()

    patches = {
        _W + ".config": cfg,
        _W + ".get_conn": mock_gc,
        _W + ".Profile": mock_profile,
        _W + ".get_unscored_vacancies": {"return_value": vacancies},
        _W + ".get_today_scored_count_by_source": {"side_effect": count_by_source_fn},
        _W + ".score_vacancy_llm": {"new_callable": AsyncMock, "side_effect": mock_score},
        _W + ".save_score": {"return_value": None},
        _W + ".get_policy": {
            "return_value": {"threshold_low": 5, "threshold_high": 8, "daily_limit": 100}
        },
        _W + ".get_today_auto_count": {"return_value": 0},
        _W + ".has_successful_apply_for_job": {"return_value": False},
        _W + ".has_any_action_for_job": {"return_value": False},
        _W + ".save_action": {"return_value": 1},
        _W + ".emit": {"return_value": None},
        _W + ".get_today_hold_count": {"return_value": 0},
        _W + ".was_hold_notification_sent_today": {"return_value": True},
        _W + ".was_scoring_cap_notification_sent_today": {"return_value": True},
        _W + ".was_tg_scoring_cap_notification_sent_today": {"return_value": True},
        _W + ".was_cover_letter_cap_notification_sent_today": {"return_value": True},
        _W + ".get_today_cover_letter_count": {"return_value": 0},
        _W + ".get_resume_text": {"return_value": "resume"},
        _W + ".should_skip_scoring": {"return_value": (False, "")},
        _W + ".get_existing_score_by_hh_vacancy_id": {"return_value": None},
    }

    with contextlib.ExitStack() as stack:
        for target, val in patches.items():
            if isinstance(val, dict):
                stack.enter_context(patch(target, **val))
            else:
                stack.enter_context(patch(target, val))
        stack.enter_context(
            patch(_W + ".asyncio.sleep",
                  new_callable=AsyncMock, side_effect=asyncio.CancelledError)
        )
        from capabilities.career_os.skills.match_scoring.worker import scoring_worker
        try:
            await scoring_worker(mock_bot)
        except asyncio.CancelledError:
            pass

    return scored_ids


class TestScoringCapSplit:
    @pytest.mark.asyncio
    async def test_tg_scored_when_hh_cap_exhausted(self):
        """TG vacancy scored even when HH cap is at its limit."""
        tg_vac = _make_vacancy(10, "telegram_forward")
        hh_vac = _make_vacancy(11, "hh")

        def count_fn(conn, source):
            return 2 if source == "hh" else 0  # HH cap=2/2, TG=0/20

        scored = await _run_worker_once(
            AsyncMock(), _make_cfg(hh_cap=2, tg_cap=20),
            [tg_vac, hh_vac], count_fn
        )
        assert 10 in scored, "TG vacancy should be scored when HH cap is exhausted"
        assert 11 not in scored, "HH vacancy should be skipped when HH cap is exhausted"

    @pytest.mark.asyncio
    async def test_hh_skipped_when_hh_cap_exhausted(self):
        """HH vacancy skipped when HH cap is at limit."""
        hh_vac = _make_vacancy(11, "hh")

        def count_fn(conn, source):
            return 2 if source == "hh" else 0

        scored = await _run_worker_once(
            AsyncMock(), _make_cfg(hh_cap=2, tg_cap=20),
            [hh_vac], count_fn
        )
        assert 11 not in scored

    @pytest.mark.asyncio
    async def test_tg_skipped_when_tg_cap_exhausted(self):
        """TG vacancy skipped when TG cap is at limit."""
        tg_vac = _make_vacancy(10, "telegram_forward")

        def count_fn(conn, source):
            return 3 if source == "telegram_forward" else 0  # TG cap=3/3

        scored = await _run_worker_once(
            AsyncMock(), _make_cfg(hh_cap=40, tg_cap=3),
            [tg_vac], count_fn
        )
        assert 10 not in scored

    @pytest.mark.asyncio
    async def test_hh_scored_when_tg_cap_exhausted(self):
        """HH vacancy scored even when TG cap is exhausted."""
        hh_vac = _make_vacancy(11, "hh")
        tg_vac = _make_vacancy(10, "telegram_forward")

        def count_fn(conn, source):
            return 3 if source == "telegram_forward" else 0  # TG cap=3/3, HH=0/40

        scored = await _run_worker_once(
            AsyncMock(), _make_cfg(hh_cap=40, tg_cap=3),
            [hh_vac, tg_vac], count_fn
        )
        assert 11 in scored, "HH vacancy should be scored when TG cap is exhausted"
        assert 10 not in scored, "TG vacancy should be skipped when TG cap is exhausted"
