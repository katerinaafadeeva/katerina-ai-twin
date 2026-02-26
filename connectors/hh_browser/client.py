"""HH.ru Playwright browser client — lazy import, async context manager.

Playwright is imported lazily inside the session() context manager so that
importing this module at startup does NOT require Playwright to be installed
when HH_APPLY_ENABLED=false.

Usage:
    from connectors.hh_browser.client import HHBrowserClient

    async with HHBrowserClient().session(storage_state_path) as context:
        page = await context.new_page()
        result = await apply_to_vacancy(page, url, letter)
"""

import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Realistic browser UA — do not log, do not commit real credentials
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Viewport matching a typical laptop screen
_VIEWPORT = {"width": 1280, "height": 800}


class HHBrowserClient:
    """Async context manager wrapping a Playwright browser session.

    A new browser is launched for each call to session().
    Storage state is loaded from *storage_state_path* if the file exists,
    giving authenticated access without re-login.
    """

    @asynccontextmanager
    async def session(self, storage_state_path: str):
        """Yield a BrowserContext with auth state loaded.

        Args:
            storage_state_path: Path to JSON file saved by bootstrap.py.
                                 If the file does not exist, session is unauthenticated.
        """
        # Lazy import — playwright not required unless HH_APPLY_ENABLED=true
        from playwright.async_api import async_playwright  # noqa: PLC0415

        storage_state = storage_state_path if os.path.exists(storage_state_path) else None
        if not storage_state:
            logger.warning(
                "Storage state not found at %s — browser session will be unauthenticated",
                storage_state_path,
            )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                storage_state=storage_state,
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
                locale="ru-RU",
            )
            try:
                logger.info("Browser context opened (auth=%s)", storage_state is not None)
                yield context
            finally:
                await context.close()
                await browser.close()
                logger.info("Browser context closed")
