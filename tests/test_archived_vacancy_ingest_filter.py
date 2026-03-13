"""Tests for archived vacancy filtering at the HH ingest layer.

Covers:
- ingest_hh_vacancies() skips items with archived=True
- ingest_hh_vacancies() processes items with archived=False normally
- HHApiClient.get_vacancy() is called correctly (unit test)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.career_os.skills.vacancy_ingest_hh.handler import ingest_hh_vacancies
from capabilities.career_os.models import Profile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(hh_id: str, name: str = "PM", archived: bool = False) -> dict:
    return {
        "id": hh_id,
        "name": name,
        "archived": archived,
        "employer": {"name": "TestCo"},
        "snippet": {"requirement": "Python", "responsibility": "Lead"},
        "salary": None,
        "area": {"name": "Москва"},
        "schedule": {"name": "Полный день"},
        "alternate_url": f"https://hh.ru/vacancy/{hh_id}",
    }


@pytest.fixture()
def mock_profile(tmp_path):
    """Minimal Profile fixture that passes pre-filter checks."""
    profile_data = {
        "name": "Test User",
        "summary": "Experienced PM",
        "skills": ["управление проектами"],
        "negative_signals": [],
        "industries_excluded": [],
    }
    import json
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(profile_data))
    return Profile.from_file(str(p))


# ---------------------------------------------------------------------------
# Ingest-layer archived filter
# ---------------------------------------------------------------------------

class TestIngestArchivedFilter:

    def test_archived_vacancy_is_not_ingested(self, mock_profile):
        """Vacancies with archived=True must be counted in 'archived' and not saved."""
        item = _make_item("111", archived=True)

        with (
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_hh_vacancy_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.save_hh_vacancy") as mock_save,
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.get_conn"),
        ):
            counts = ingest_hh_vacancies([item], mock_profile)

        assert counts["archived"] == 1
        assert counts["new"] == 0
        mock_save.assert_not_called()

    def test_active_vacancy_is_ingested(self, mock_profile):
        """Vacancies with archived=False (or missing) must pass through to save."""
        item = _make_item("222", archived=False)

        with (
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_hh_vacancy_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_canonical_key_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.save_hh_vacancy", return_value=(1, True)),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.get_conn"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.emit"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score", return_value=(True, "")),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score_advanced", return_value=(True, "")),
        ):
            counts = ingest_hh_vacancies([item], mock_profile)

        assert counts["new"] == 1
        assert counts["archived"] == 0

    def test_missing_archived_field_treated_as_active(self, mock_profile):
        """Items without 'archived' key must not be filtered (treat as active)."""
        item = _make_item("333")
        item.pop("archived", None)  # ensure key is absent

        with (
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_hh_vacancy_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_canonical_key_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.save_hh_vacancy", return_value=(1, True)),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.get_conn"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.emit"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score", return_value=(True, "")),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score_advanced", return_value=(True, "")),
        ):
            counts = ingest_hh_vacancies([item], mock_profile)

        assert counts["archived"] == 0
        assert counts["new"] == 1

    def test_mixed_batch_counts_correctly(self, mock_profile):
        """Batch with 2 active + 1 archived → archived=1, total=3."""
        items = [
            _make_item("1", archived=False),
            _make_item("2", archived=True),
            _make_item("3", archived=False),
        ]

        with (
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_hh_vacancy_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.is_canonical_key_ingested", return_value=False),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.save_hh_vacancy", return_value=(1, True)),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.get_conn"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.emit"),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score", return_value=(True, "")),
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.should_score_advanced", return_value=(True, "")),
        ):
            counts = ingest_hh_vacancies(items, mock_profile)

        assert counts["total"] == 3
        assert counts["archived"] == 1
        assert counts["new"] == 2

    def test_archived_key_always_present_in_counts(self, mock_profile):
        """counts dict must always include 'archived' key even if 0."""
        with (
            patch("capabilities.career_os.skills.vacancy_ingest_hh.handler.get_conn"),
        ):
            counts = ingest_hh_vacancies([], mock_profile)

        assert "archived" in counts
        assert counts["archived"] == 0


# ---------------------------------------------------------------------------
# HHApiClient.get_vacancy unit test
# ---------------------------------------------------------------------------

class TestHHApiClientGetVacancy:

    @pytest.mark.asyncio
    async def test_get_vacancy_calls_correct_endpoint(self):
        from connectors.hh_api import HHApiClient

        client = HHApiClient(user_agent="TestAgent/1.0")
        expected_response = {"id": "123456", "archived": False, "name": "PM"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=expected_response) as mock_req:
            result = await client.get_vacancy("123456")

        assert result == expected_response
        call_args = mock_req.call_args
        assert "/vacancies/123456" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_vacancy_returns_none_on_failure(self):
        from connectors.hh_api import HHApiClient

        client = HHApiClient(user_agent="TestAgent/1.0")

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=None):
            result = await client.get_vacancy("999")

        assert result is None
