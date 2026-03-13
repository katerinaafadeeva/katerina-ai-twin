"""HH.ru API client — vacancy search with rate limiting and retry.

Anonymous access only (no OAuth). Requires User-Agent header.
Rate limited: max 1 request per second.
No business logic — pure HTTP transport.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

HH_BASE_URL = "https://api.hh.ru"
DEFAULT_PER_PAGE = 100
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # exponential backoff base (seconds)


class HHApiClient:
    """Async client for HH.ru vacancy search API.

    Features:
    - Rate limiting: enforces ≥1 second between requests
    - Retry with exponential backoff on HTTP 429 and 5xx
    - Max 3 retries per request, 30s timeout
    - Pagination up to max_pages pages (100 items/page)
    """

    def __init__(self, user_agent: str, max_pages: int = 5):
        self.user_agent = user_agent
        self.max_pages = max_pages
        self._last_request_time: float = 0.0

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests (≤1 req/sec)."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Dict[str, Any],
    ) -> Optional[Dict]:
        """Make a single HTTP GET request with retry logic.

        Returns:
            Parsed JSON dict on success, None on permanent failure.
        """
        for attempt in range(MAX_RETRIES):
            await self._rate_limit()
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "HH API rate limit (429), retry in %.1fs (attempt %d/%d)",
                        delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                elif response.status_code >= 500:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "HH API server error %d, retry in %.1fs (attempt %d/%d)",
                        response.status_code, delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "HH API unexpected status %d for %s",
                        response.status_code, url,
                    )
                    return None
            except httpx.TimeoutException:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "HH API timeout, retry in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(delay)
            except httpx.HTTPError as exc:
                logger.error("HH API HTTP error: %s", exc)
                return None

        logger.error("HH API max retries (%d) exhausted for %s", MAX_RETRIES, url)
        return None

    async def get_vacancy(self, vacancy_id: str) -> Optional[Dict]:
        """Fetch a single vacancy by HH ID from the detail endpoint.

        Returns:
            Vacancy dict on success (includes 'archived' bool, 'type', etc.),
            or None if the request fails or vacancy is not found.
        """
        async with httpx.AsyncClient() as client:
            return await self._request(
                client,
                f"{HH_BASE_URL}/vacancies/{vacancy_id}",
                {},
            )

    async def search_vacancies(self, query_params: Dict[str, str]) -> List[Dict]:
        """Search HH.ru vacancies with automatic pagination.

        Args:
            query_params: HH API search parameters (text, area, schedule, etc.)
                          See https://api.hh.ru/openapi/redoc#tag/Vacancy-search

        Returns:
            Flat list of vacancy dicts from HH API response items.
        """
        all_items: List[Dict] = []
        params: Dict[str, Any] = {
            **query_params,
            "per_page": DEFAULT_PER_PAGE,
            "page": 0,
        }
        # Default: only vacancies published in the last 7 days
        if "period" not in params:
            params["period"] = 7

        async with httpx.AsyncClient() as client:
            for page in range(self.max_pages):
                params["page"] = page
                data = await self._request(client, f"{HH_BASE_URL}/vacancies", params)
                if data is None:
                    break

                items = data.get("items", [])
                if not items:
                    break

                all_items.extend(items)
                logger.info(
                    "HH search page %d/%d: %d items (running total: %d)",
                    page, self.max_pages - 1, len(items), len(all_items),
                )

                # Stop if HH reports no more pages
                total_pages = data.get("pages", 0)
                if page + 1 >= total_pages:
                    break

        return all_items
