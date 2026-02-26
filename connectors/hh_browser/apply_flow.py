"""HH.ru apply flow — pure browser automation, zero LLM calls.

Takes a Playwright Page object and performs the apply sequence.
Returns an ApplyResult describing the outcome.

Design rules:
- No logging of cookies, auth tokens, or personal credentials
- All selectors in selectors.py (single place to update)
- Playwright imported lazily (never at module level)
- Every DOM interaction wrapped in try/except at the caller level
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from connectors.hh_browser import selectors

logger = logging.getLogger(__name__)

# Timeout for most DOM operations (ms)
_DEFAULT_TIMEOUT_MS = 10_000
# Shorter timeout for optional elements (already-applied, captcha check)
_QUICK_TIMEOUT_MS = 3_000


class ApplyStatus(str, Enum):
    DONE = "done"                      # Application submitted successfully
    ALREADY_APPLIED = "already_applied"  # Candidate already applied to this vacancy
    MANUAL_REQUIRED = "manual_required"  # Apply button absent — needs operator attention
    CAPTCHA = "captcha"                # Captcha detected — stop entire batch
    SESSION_EXPIRED = "session_expired"  # Not logged in — need to re-bootstrap
    FAILED = "failed"                  # Unexpected error during flow


@dataclass
class ApplyResult:
    status: ApplyStatus
    error: str = ""
    apply_url: str = ""


async def _is_captcha_present(page) -> bool:
    """Check if any captcha element is visible on the page."""
    for selector in (selectors.CAPTCHA_WRAPPER, selectors.RECAPTCHA_IFRAME, selectors.SMARTCAPTCHA_IFRAME):
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                return True
        except Exception:
            pass
    return False


async def _is_session_expired(page) -> bool:
    """Check if we've been redirected to the login page."""
    try:
        url = page.url
        if "login" in url or "account" in url.split("?")[0].split("/")[-1:][0:1]:
            return True
        el = await page.query_selector(selectors.AUTH_LOGIN_BUTTON)
        if el and await el.is_visible():
            return True
    except Exception:
        pass
    return False


async def apply_to_vacancy(page, vacancy_url: str, cover_letter: str = "") -> ApplyResult:
    """Navigate to vacancy page and submit application.

    Args:
        page:          Playwright Page (already has auth storage state loaded).
        vacancy_url:   Full URL of the HH.ru vacancy (https://hh.ru/vacancy/{id}).
        cover_letter:  Cover letter text to insert (may be empty).

    Returns:
        ApplyResult with status and optional error message.
    """
    apply_url = vacancy_url

    try:
        logger.info("Navigating to vacancy: %s", vacancy_url)
        await page.goto(vacancy_url, wait_until="domcontentloaded", timeout=30_000)

        # --- Session check ---
        if await _is_session_expired(page):
            logger.warning("Session expired — cannot apply")
            return ApplyResult(status=ApplyStatus.SESSION_EXPIRED, apply_url=apply_url)

        # --- Captcha check before clicking ---
        if await _is_captcha_present(page):
            logger.warning("Captcha detected on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # --- Already applied? ---
        try:
            already = await page.wait_for_selector(
                selectors.ALREADY_APPLIED, timeout=_QUICK_TIMEOUT_MS
            )
            if already and await already.is_visible():
                logger.info("Already applied to %s", vacancy_url)
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass  # Selector not present = not yet applied, continue

        # --- Find apply button ---
        apply_btn = None
        for selector in (selectors.APPLY_BUTTON, selectors.APPLY_BUTTON_BOTTOM):
            try:
                el = await page.wait_for_selector(selector, timeout=_QUICK_TIMEOUT_MS)
                if el and await el.is_visible():
                    apply_btn = el
                    break
            except Exception:
                continue

        if apply_btn is None:
            logger.warning("Apply button not found on %s — manual action required", vacancy_url)
            return ApplyResult(
                status=ApplyStatus.MANUAL_REQUIRED,
                error="Apply button not found",
                apply_url=apply_url,
            )

        # --- Click apply button ---
        await apply_btn.click()
        logger.debug("Clicked apply button on %s", vacancy_url)

        # --- Post-click captcha check ---
        if await _is_captcha_present(page):
            logger.warning("Captcha appeared after click on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # --- Fill cover letter if textarea is present ---
        if cover_letter:
            try:
                textarea = await page.wait_for_selector(
                    selectors.COVER_LETTER_TEXTAREA, timeout=_QUICK_TIMEOUT_MS
                )
                if textarea and await textarea.is_visible():
                    await textarea.fill(cover_letter)
                    logger.debug("Cover letter filled (%d chars)", len(cover_letter))
            except Exception:
                logger.debug("Cover letter textarea not found — submitting without it")

        # --- Submit ---
        submit_btn = await page.wait_for_selector(
            selectors.SUBMIT_BUTTON, timeout=_DEFAULT_TIMEOUT_MS
        )
        await submit_btn.click()
        logger.info("Application submitted for %s", vacancy_url)

        # --- Final captcha check (some sites show captcha after submit) ---
        if await _is_captcha_present(page):
            logger.warning("Captcha after submit on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)

    except Exception as exc:
        logger.warning("Apply flow failed for %s: %s", vacancy_url, exc)
        return ApplyResult(
            status=ApplyStatus.FAILED,
            error=str(exc)[:500],
            apply_url=apply_url,
        )
