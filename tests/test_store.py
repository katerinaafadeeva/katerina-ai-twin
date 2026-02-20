"""Tests for match_scoring/store.py — idempotency, unscored query, get_score."""

from capabilities.career_os.skills.match_scoring.store import (
    get_score,
    get_unscored_vacancies,
    save_score,
)


def _insert_vacancy(conn, job_id: int, raw_text: str = "Test vacancy text") -> None:
    conn.execute(
        "INSERT INTO job_raw (id, raw_text, source, source_message_id) VALUES (?, ?, ?, ?)",
        (job_id, raw_text, "telegram_forward", f"src_{job_id}"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get_unscored_vacancies
# ---------------------------------------------------------------------------


def test_unscored_returns_empty_when_no_vacancies(db_conn):
    result = get_unscored_vacancies(db_conn)
    assert result == []


def test_unscored_returns_inserted_vacancy(db_conn):
    _insert_vacancy(db_conn, job_id=1)
    result = get_unscored_vacancies(db_conn)
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_unscored_disappears_after_save_score(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)
    assert len(get_unscored_vacancies(db_conn)) == 1

    save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc123", model="llm_call",
        prompt_version="scoring_v1", input_tokens=0, output_tokens=0, cost_usd=0.0,
    )
    db_conn.commit()

    assert get_unscored_vacancies(db_conn) == []


def test_unscored_ordered_oldest_first(db_conn):
    # Insert with explicit created_at so ordering is deterministic
    for i, ts in [(3, "2026-01-03"), (1, "2026-01-01"), (2, "2026-01-02")]:
        db_conn.execute(
            "INSERT INTO job_raw (id, raw_text, source, source_message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (i, "text", "tg", f"src_{i}", ts),
        )
    db_conn.commit()

    result = get_unscored_vacancies(db_conn)
    ids = [r["id"] for r in result]
    assert ids == [1, 2, 3]


def test_unscored_respects_scorer_version(db_conn, sample_scoring_output):
    """A vacancy scored with v1 is NOT returned for v1 but IS returned for v2."""
    _insert_vacancy(db_conn, job_id=1)

    save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
        scorer_version="v1",
    )
    db_conn.commit()

    assert get_unscored_vacancies(db_conn, scorer_version="v1") == []
    assert len(get_unscored_vacancies(db_conn, scorer_version="v2")) == 1


# ---------------------------------------------------------------------------
# save_score — idempotency
# ---------------------------------------------------------------------------


def test_save_score_returns_nonzero_rowid_on_insert(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)
    rowid = save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
    )
    db_conn.commit()
    assert rowid > 0


def test_save_score_idempotent_second_insert_returns_zero(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)

    first = save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
    )
    db_conn.commit()
    assert first > 0

    second = save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
    )
    db_conn.commit()
    assert second == 0


def test_save_score_persists_correct_values(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)
    save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="myhash", model="llm_call", prompt_version="scoring_v1",
        input_tokens=10, output_tokens=20, cost_usd=0.001,
    )
    db_conn.commit()

    row = dict(db_conn.execute(
        "SELECT * FROM job_scores WHERE job_raw_id = 1"
    ).fetchone())

    assert row["score"] == sample_scoring_output.score
    assert row["explanation"] == sample_scoring_output.explanation
    assert row["profile_hash"] == "myhash"
    assert row["model"] == "llm_call"
    assert row["prompt_version"] == "scoring_v1"
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 20


# ---------------------------------------------------------------------------
# get_score
# ---------------------------------------------------------------------------


def test_get_score_returns_none_when_not_scored(db_conn):
    _insert_vacancy(db_conn, job_id=1)
    assert get_score(db_conn, job_raw_id=1) is None


def test_get_score_returns_dict_after_save(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)
    save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
    )
    db_conn.commit()

    record = get_score(db_conn, job_raw_id=1)
    assert record is not None
    assert record["score"] == sample_scoring_output.score
    assert record["scorer_version"] == "v1"


def test_get_score_respects_scorer_version(db_conn, sample_scoring_output):
    _insert_vacancy(db_conn, job_id=1)
    save_score(
        db_conn, job_raw_id=1, result=sample_scoring_output,
        profile_hash="abc", model="llm_call", prompt_version="scoring_v1",
        input_tokens=0, output_tokens=0, cost_usd=0.0,
        scorer_version="v1",
    )
    db_conn.commit()

    assert get_score(db_conn, job_raw_id=1, scorer_version="v1") is not None
    assert get_score(db_conn, job_raw_id=1, scorer_version="v2") is None
