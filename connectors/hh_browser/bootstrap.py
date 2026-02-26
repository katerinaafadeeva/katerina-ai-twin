"""One-time HH.ru authentication bootstrap.

Run this script once to log in to HH.ru manually and save the browser
storage state (cookies + localStorage) for subsequent headless sessions.

Usage:
    python -m connectors.hh_browser.bootstrap

The script opens a visible (non-headless) browser window.
Log in to hh.ru manually, then press Enter in the terminal.
Storage state is saved to the path configured in HH_STORAGE_STATE_PATH
(default: identity/hh_storage_state.json — gitignored).

SECURITY:
- The saved file contains session cookies. Treat it as a secret.
- Never commit identity/hh_storage_state.json (it is in .gitignore).
- Rotate by deleting the file and running bootstrap again.
"""

import asyncio
import os
import sys


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    # Import config lazily to support running without full env
    storage_path = os.getenv("HH_STORAGE_STATE_PATH", "identity/hh_storage_state.json")
    os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)

    print(f"Bootstrap: storage will be saved to {storage_path}")
    print("A browser window will open. Log in to hh.ru, then press Enter here.")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context(locale="ru-RU")
        page = await context.new_page()

        await page.goto("https://hh.ru/login")

        print("\nBrowser is open. Please log in to hh.ru...")
        input("Press Enter after you have logged in successfully: ")

        await context.storage_state(path=storage_path)
        print(f"\nAuth state saved to: {storage_path}")
        print("You can now start the bot with HH_APPLY_ENABLED=true")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
