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
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from connectors.hh_browser import selectors

logger = logging.getLogger(__name__)

# Timeout for the multi-outcome wait after clicking apply (ms)
_OUTCOME_TIMEOUT_MS = 30_000
# Shorter timeout for optional/quick checks (ms)
_QUICK_TIMEOUT_MS = 3_000
# Default timeout for individual DOM operations (ms)
_DEFAULT_TIMEOUT_MS = 10_000

# Directory for failure artifacts (screenshot + HTML snapshot)
_ARTIFACT_DIR = "/tmp/hh_apply_artifacts"

# Combined CSS selector — wait for the first of these to appear post-click.
# Covers: popup opened | direct success toast | response-sent label |
#         already-applied state | captcha.
_POST_CLICK_OUTCOMES = ", ".join([
    selectors.SUBMIT_BUTTON,
    selectors.SUCCESS_TOAST,
    selectors.RESPONSE_SENT_LABEL,
    selectors.ALREADY_APPLIED,
    selectors.CAPTCHA_WRAPPER,
])


class ApplyStatus(str, Enum):
    DONE = "done"                        # Application submitted with cover letter
    DONE_WITHOUT_LETTER = "done_without_letter"  # Submitted; no letter field found
    ALREADY_APPLIED = "already_applied"  # Candidate already applied
    MANUAL_REQUIRED = "manual_required"  # Apply button absent — operator needed
    CAPTCHA = "captcha"                  # Captcha detected — stop entire batch
    SESSION_EXPIRED = "session_expired"  # Not logged in — re-bootstrap required
    FAILED = "failed"                    # Unexpected error during flow


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


async def _save_fail_artifacts(page, vacancy_url: str) -> str:
    """Save screenshot + HTML snapshot on failure. Returns suffix with paths."""
    try:
        os.makedirs(_ARTIFACT_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_id = vacancy_url.rstrip("/").split("/")[-1]
        base = os.path.join(_ARTIFACT_DIR, f"fail_{safe_id}_{ts}")
        screenshot_path = base + ".png"
        html_path = base + ".html"
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            screenshot_path = "(screenshot failed)"
        try:
            html = await page.content()
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(html)
        except Exception as exc:
            logger.warning("HTML snapshot failed: %s", exc)
            html_path = "(html failed)"
        logger.info("Failure artifacts: %s | %s", screenshot_path, html_path)
        return f" [screenshot={screenshot_path} html={html_path}]"
    except Exception as exc:
        logger.warning("_save_fail_artifacts error: %s", exc)
        return ""


async def apply_to_vacancy(page, vacancy_url: str, cover_letter: str = "") -> ApplyResult:
    """Navigate to vacancy page and submit application.

    Post-click multi-outcome wait (30 s) handles four HH paths:
      1. Popup appeared → fill cover letter (if field present) → submit → DONE
      2. Success toast / response-sent label → DONE (quick apply, no popup)
      3. Already-applied state → ALREADY_APPLIED
      4. Captcha → CAPTCHA (stop batch)
      5. 30 s timeout → save screenshot+HTML → FAILED

    Cover letter strategy (per user decision):
      - If popup textarea visible → fill → DONE
      - If textarea absent → submit without letter → DONE_WITHOUT_LETTER + warning log
      - "done_without_letter" does not retry; apply IS submitted

    Args:
        page:          Playwright Page (already has auth storage state loaded).
        vacancy_url:   Full URL of the HH.ru vacancy (https://hh.ru/vacancy/{id}).
        cover_letter:  Cover letter text to insert (may be empty).

    Returns:
        ApplyResult with status and optional error/artifact paths.
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

        # --- Already applied? (quick pre-click check) ---
        try:
            already = await page.wait_for_selector(
                selectors.ALREADY_APPLIED, timeout=_QUICK_TIMEOUT_MS
            )
            if already and await already.is_visible():
                logger.info("Already applied to %s", vacancy_url)
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass  # Not present = not yet applied, continue

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

        # --- Multi-outcome wait (30 s) ---
        # Waits for the first of: popup | toast | already-applied | captcha.
        # This replaces the old narrow wait for submit-popup only (was 10 s).
        try:
            await page.wait_for_selector(_POST_CLICK_OUTCOMES, timeout=_OUTCOME_TIMEOUT_MS)
        except Exception:
            # No recognisable outcome in 30 s — save artifacts and fail.
            artifact_suffix = await _save_fail_artifacts(page, vacancy_url)
            error_msg = (
                f"Timeout after {_OUTCOME_TIMEOUT_MS // 1000}s waiting for "
                f"post-click outcome{artifact_suffix}"
            )
            logger.warning("Apply flow timeout on %s: %s", vacancy_url, error_msg)
            return ApplyResult(status=ApplyStatus.FAILED, error=error_msg, apply_url=apply_url)

        # --- Identify which outcome appeared ---

        # Captcha post-click
        if await _is_captcha_present(page):
            logger.warning("Captcha appeared after click on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # Success toast (quick apply — letter field not shown by HH)
        try:
            toast = await page.query_selector(selectors.SUCCESS_TOAST)
            if toast and await toast.is_visible():
                logger.info("Success toast detected on %s (quick apply)", vacancy_url)
                if cover_letter:
                    logger.warning(
                        "no_cover_letter_field: quick-apply path on %s — submitted without letter",
                        vacancy_url,
                    )
                    return ApplyResult(
                        status=ApplyStatus.DONE_WITHOUT_LETTER, apply_url=apply_url
                    )
                return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)
        except Exception:
            pass

        # Response-sent label (alternative success indicator)
        try:
            sent = await page.query_selector(selectors.RESPONSE_SENT_LABEL)
            if sent and await sent.is_visible():
                logger.info("Response-sent label detected on %s", vacancy_url)
                return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)
        except Exception:
            pass

        # Already-applied state appeared after click
        try:
            already2 = await page.query_selector(selectors.ALREADY_APPLIED)
            if already2 and await already2.is_visible():
                logger.info("Already-applied state on %s (appeared after click)", vacancy_url)
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass

        # --- Popup path: submit button is visible ---
        submit_btn = None
        try:
            submit_btn = await page.query_selector(selectors.SUBMIT_BUTTON)
        except Exception:
            pass

        if submit_btn is None or not await submit_btn.is_visible():
            artifact_suffix = await _save_fail_artifacts(page, vacancy_url)
            logger.warning("Unknown post-click outcome on %s%s", vacancy_url, artifact_suffix)
            return ApplyResult(
                status=ApplyStatus.FAILED,
                error=f"Unknown post-click outcome{artifact_suffix}",
                apply_url=apply_url,
            )

        # --- Fill cover letter (if textarea present in popup) ---
        letter_filled = False
        try:
            textarea = await page.query_selector(selectors.COVER_LETTER_TEXTAREA)
            if textarea and await textarea.is_visible():
                if cover_letter:
                    await textarea.fill(cover_letter)
                    value = await textarea.input_value()
                    if value:
                        letter_filled = True
                        logger.info("Cover letter filled (%d chars)", len(value))
                    else:
                        logger.warning(
                            "Cover letter fill may have failed — value empty after fill on %s",
                            vacancy_url,
                        )
                else:
                    logger.debug("Cover letter textarea found but no letter text provided")
            else:
                if cover_letter:
                    logger.warning(
                        "no_cover_letter_field: popup has no visible textarea on %s — "
                        "submitting without letter",
                        vacancy_url,
                    )
        except Exception as exc:
            logger.warning("Cover letter fill error on %s: %s", vacancy_url, exc)

        # --- Submit ---
        await submit_btn.click()
        logger.info("Application submitted for %s", vacancy_url)

        # --- Final captcha check ---
        if await _is_captcha_present(page):
            logger.warning("Captcha after submit on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # Return DONE or DONE_WITHOUT_LETTER based on whether letter was filled
        if cover_letter and not letter_filled:
            return ApplyResult(status=ApplyStatus.DONE_WITHOUT_LETTER, apply_url=apply_url)
        return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)

    except Exception as exc:
        logger.warning("Apply flow failed for %s: %s", vacancy_url, exc)
        return ApplyResult(
            status=ApplyStatus.FAILED,
            error=str(exc)[:500],
            apply_url=apply_url,
        )
