"""Tests for connectors/hh_api.py — HHApiClient.

Covers:
- Successful single-page search
- Pagination stops at max_pages
- Pagination stops when items=[]
- Pagination stops when page+1 >= total_pages
- 200 response returns items
- 429 triggers retry then succeeds
- 5xx triggers retry then succeeds
- All retries exhausted returns empty list
- Timeout triggers retry then succeeds
- Non-retryable error (4xx != 429) returns None immediately
- User-Agent header is sent
- rate_limit: no sleep when interval is large enough
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from connectors.hh_api import (
    DEFAULT_PER_PAGE,
    HH_BASE_URL,
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL,
    RETRY_BASE_DELAY,
    HHApiClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(items: list, pages: int = 1) -> dict:
    """Build a minimal HH API page response."""
    return {"items": items, "pages": pages, "found": len(items)}


def _make_vacancy(id: str = "1") -> dict:
    return {"id": id, "name": "Product Manager"}


def _mock_response(status_code: int, json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


# ---------------------------------------------------------------------------
# search_vacancies: pagination and stopping conditions
# ---------------------------------------------------------------------------


class TestSearchVacanciesPagination:
    @pytest.mark.asyncio
    async def test_single_page_returns_items(self):
        """One page with 2 items → returns both."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)
        page_data = _make_page([_make_vacancy("1"), _make_vacancy("2")], pages=1)

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, page_data)

            results = await client.search_vacancies({"text": "PM"})

        assert len(results) == 2
        assert results[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_stops_at_max_pages(self):
        """With max_pages=2 and server reporting 5 pages, fetches only 2."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=2)

        def _page_response(url, params, headers, timeout):
            page = params.get("page", 0)
            return _mock_response(200, _make_page([_make_vacancy(str(page))], pages=5))

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = _page_response

            results = await client.search_vacancies({"text": "PM"})

        assert len(results) == 2  # 1 item per page × 2 pages

    @pytest.mark.asyncio
    async def test_stops_when_items_empty(self):
        """If a page returns items=[], stop early."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)
        responses = [
            _mock_response(200, _make_page([_make_vacancy("1")], pages=5)),
            _mock_response(200, _make_page([], pages=5)),  # empty → stop
        ]

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = responses

            results = await client.search_vacancies({"text": "PM"})

        assert len(results) == 1
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_stops_when_page_plus1_gte_total_pages(self):
        """If page+1 >= total_pages, stop — even if max_pages allows more."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)

        def _page_response(url, params, headers, timeout):
            page = params.get("page", 0)
            # Server says there are only 2 pages total
            return _mock_response(200, _make_page([_make_vacancy(str(page))], pages=2))

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = _page_response

            results = await client.search_vacancies({"text": "PM"})

        # Page 0: page+1=1 < 2 → continue. Page 1: page+1=2 >= 2 → stop.
        assert len(results) == 2
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_on_none_response(self):
        """If _request returns None, search_vacancies returns []."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            # Return a 4xx so _request returns None
            mock_client.get.return_value = _mock_response(403)

            results = await client.search_vacancies({"text": "PM"})

        assert results == []

    @pytest.mark.asyncio
    async def test_default_period_added(self):
        """search_vacancies adds period=7 if not in query_params."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=1)
        page_data = _make_page([])

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, page_data)

            await client.search_vacancies({"text": "PM"})

        called_params = mock_client.get.call_args.kwargs.get("params") or mock_client.get.call_args[1].get("params")
        assert called_params["period"] == 7

    @pytest.mark.asyncio
    async def test_user_agent_header_sent(self):
        """Verify User-Agent header is passed to every request."""
        client = HHApiClient(user_agent="MyBot/1.0", max_pages=1)
        page_data = _make_page([])

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, page_data)

            await client.search_vacancies({"text": "PM"})

        called_headers = mock_client.get.call_args.kwargs.get("headers") or mock_client.get.call_args[1].get("headers")
        assert called_headers["User-Agent"] == "MyBot/1.0"


# ---------------------------------------------------------------------------
# _request: retry logic
# ---------------------------------------------------------------------------


class TestRequestRetry:
    @pytest.mark.asyncio
    async def test_429_triggers_retry_then_succeeds(self):
        """429 on first attempt → retry → 200 on second."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)
        page_data = _make_page([_make_vacancy("1")])
        responses = [
            _mock_response(429),
            _mock_response(200, page_data),
        ]

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = responses

            with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
                result = await client.search_vacancies({"text": "PM"})

        assert len(result) == 1
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_5xx_triggers_retry_then_succeeds(self):
        """500 on first attempt → retry → 200 on second."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)
        page_data = _make_page([_make_vacancy("1")])
        responses = [
            _mock_response(500),
            _mock_response(200, page_data),
        ]

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = responses

            with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
                result = await client.search_vacancies({"text": "PM"})

        assert len(result) == 1
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_empty(self):
        """3 consecutive 429s → retries exhausted → empty list."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(429)

            with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
                result = await client.search_vacancies({"text": "PM"})

        assert result == []
        assert mock_client.get.call_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry_then_succeeds(self):
        """TimeoutException on first attempt → retry → 200."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)
        page_data = _make_page([_make_vacancy("1")])

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                httpx.TimeoutException("timeout"),
                _mock_response(200, page_data),
            ]

            with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
                result = await client.search_vacancies({"text": "PM"})

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_non_retryable_4xx_returns_none_immediately(self):
        """403 (not 429) → no retry, returns None immediately."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(403)

            with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
                result = await client.search_vacancies({"text": "PM"})

        # 403 → _request returns None → search returns []
        assert result == []
        # No retry: get called exactly once per attempt in _request loop
        # (403 falls through without retry → loop ends after 1 call)
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """httpx.HTTPError (network failure) → returns None, no retry."""
        client = HHApiClient(user_agent="Test/0.1", max_pages=5)

        with patch("connectors.hh_api.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.HTTPError("connection refused")

            result = await client.search_vacancies({"text": "PM"})

        assert result == []
        # HTTPError → immediate None return (no retry in loop)
        assert mock_client.get.call_count == 1


# ---------------------------------------------------------------------------
# _rate_limit: timing behaviour
# ---------------------------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_no_sleep_when_interval_elapsed(self):
        """If ≥ MIN_REQUEST_INTERVAL elapsed, _rate_limit does not sleep."""
        client = HHApiClient(user_agent="Test/0.1")
        client._last_request_time = time.monotonic() - (MIN_REQUEST_INTERVAL + 0.5)

        with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._rate_limit()

        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_when_within_interval(self):
        """If < MIN_REQUEST_INTERVAL elapsed, _rate_limit sleeps the remainder."""
        client = HHApiClient(user_agent="Test/0.1")
        # Pretend last request was 0.1s ago
        client._last_request_time = time.monotonic() - 0.1

        with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._rate_limit()

        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert 0 < sleep_arg <= MIN_REQUEST_INTERVAL

    @pytest.mark.asyncio
    async def test_last_request_time_updated(self):
        """_rate_limit always updates _last_request_time after call."""
        client = HHApiClient(user_agent="Test/0.1")
        client._last_request_time = 0.0
        before = time.monotonic()

        with patch("connectors.hh_api.asyncio.sleep", new_callable=AsyncMock):
            await client._rate_limit()

        assert client._last_request_time >= before
