"""HH.ru apply flow — pure browser automation, zero LLM calls.

Takes a Playwright Page object and performs the apply sequence.
Returns an ApplyResult describing the outcome.

Design rules:
- No logging of cookies, auth tokens, or personal credentials
- All selectors in selectors.py (single place to update)
- Playwright imported lazily (never at module level)
- Every DOM interaction wrapped in try/except at the caller level

HH apply paths (confirmed from production HTML artifacts):

  Path A — Popup:
    click apply → modal popup opens → SUBMIT_BUTTON appears →
    fill COVER_LETTER_TEXTAREA (optional) → click SUBMIT_BUTTON → DONE

  Path B — Inline (quick apply):
    click apply → page updates inline → RESPONSE_TOPIC_LINK (Чат) appears →
    INLINE_LETTER_FORM appears simultaneously (optional cover letter field) →
    fill INLINE_LETTER_TEXTAREA → click INLINE_LETTER_SUBMIT → DONE

  Both paths may be preceded by a cookies banner that must be dismissed.
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
# Directory for failure artifacts (screenshot + HTML snapshot)
_ARTIFACT_DIR = "/tmp/hh_apply_artifacts"

# Combined CSS selector waited for after clicking apply.
# First match determines which path HH used.
# Confirmed outcomes from production:
#   INLINE_LETTER_FORM + RESPONSE_TOPIC_LINK = quick-apply path
#   SUBMIT_BUTTON                             = popup path
#   SUCCESS_TOAST / RESPONSE_SENT_LABEL       = fast success without form
#   ALREADY_APPLIED                            = was already applied
#   CAPTCHA_WRAPPER                            = captcha
_POST_CLICK_OUTCOMES = ", ".join([
    selectors.INLINE_LETTER_FORM,   # quick-apply: inline letter form (Path B)
    selectors.RESPONSE_TOPIC_LINK,  # quick-apply: chat link (strong success signal)
    selectors.SUBMIT_BUTTON,        # popup: submit button inside modal (Path A)
    selectors.SUCCESS_TOAST,        # generic success toast
    selectors.RESPONSE_SENT_LABEL,  # generic success label
    selectors.ALREADY_APPLIED,      # already applied state
    selectors.CAPTCHA_WRAPPER,      # captcha appeared
])

# Diagnostic outcomes from HTML parsing (when timeout occurs)
_DIAGNOSTIC_EXTERNAL = "external_apply"
_DIAGNOSTIC_QUESTIONNAIRE = "questionnaire_required"
_DIAGNOSTIC_PHONE = "phone_verification_required"
_DIAGNOSTIC_COOKIES = "cookies_overlay"
_DIAGNOSTIC_INLINE = "inline_letter_form_appeared"
_DIAGNOSTIC_CHAT = "already_applied_with_chat"
_DIAGNOSTIC_UNKNOWN = "unknown_ui"


class ApplyStatus(str, Enum):
    DONE = "done"                        # Application submitted with cover letter
    DONE_WITHOUT_LETTER = "done_without_letter"  # Submitted; no letter field found
    ALREADY_APPLIED = "already_applied"  # Candidate already applied
    MANUAL_REQUIRED = "manual_required"  # Needs operator: external/questionnaire/phone
    CAPTCHA = "captcha"                  # Captcha detected — stop entire batch
    SESSION_EXPIRED = "session_expired"  # Not logged in — re-bootstrap required
    FAILED = "failed"                    # Unexpected error during flow


@dataclass
class ApplyResult:
    status: ApplyStatus
    error: str = ""
    apply_url: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _accept_cookies(page) -> None:
    """Dismiss the cookies consent banner if present (non-blocking)."""
    try:
        btn = await page.query_selector(selectors.COOKIES_ACCEPT)
        if btn and await btn.is_visible():
            await btn.click()
            logger.debug("Accepted cookies banner")
    except Exception:
        pass


async def _diagnose_timeout(page) -> tuple:
    """Parse page HTML after timeout to infer the actual outcome.

    Returns:
        (detected_outcome: str, page_title: str)
    """
    try:
        html = await page.content()
        title = await page.title()
    except Exception:
        return _DIAGNOSTIC_UNKNOWN, ""

    # Chat link + inline form: quick apply succeeded, form appeared but we missed it
    if selectors.RESPONSE_TOPIC_LINK.split("'")[1] in html:
        if selectors.INLINE_LETTER_FORM.split("'")[1] in html:
            return _DIAGNOSTIC_INLINE, title
        return _DIAGNOSTIC_CHAT, title

    # Inline form alone
    if selectors.INLINE_LETTER_FORM.split("'")[1] in html:
        return _DIAGNOSTIC_INLINE, title

    html_lower = html.lower()

    # External apply (employer site redirect)
    if "перейти на сайт работодателя" in html_lower or "vacancy-response-link-view-employer" in html:
        return _DIAGNOSTIC_EXTERNAL, title

    # Questionnaire / test required
    if "questionnaire" in html_lower:
        return _DIAGNOSTIC_QUESTIONNAIRE, title

    # Phone verification
    if "подтвердить телефон" in html_lower:
        return _DIAGNOSTIC_PHONE, title

    # Cookies overlay blocking
    if selectors.COOKIES_ACCEPT.split("'")[1] in html:
        return _DIAGNOSTIC_COOKIES, title

    return _DIAGNOSTIC_UNKNOWN, title


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


async def _fill_inline_letter(page, cover_letter: str, vacancy_url: str) -> bool:
    """Fill and submit the inline cover letter form (Path B).

    The inline form (vacancy-response-letter-informer) appears on the vacancy
    page after quick apply. Submitting it sends the letter to the employer chat.

    Returns:
        True if the letter was filled and submitted successfully.
    """
    try:
        textarea = await page.query_selector(selectors.INLINE_LETTER_TEXTAREA)
        if textarea and await textarea.is_visible():
            await textarea.fill(cover_letter)
            value = await textarea.input_value()
            if not value:
                logger.warning(
                    "Inline letter fill may have failed — value empty after fill on %s",
                    vacancy_url,
                )
                return False
            logger.info("Inline cover letter filled (%d chars) for %s", len(value), vacancy_url)
            submit = await page.query_selector(selectors.INLINE_LETTER_SUBMIT)
            if submit and await submit.is_visible():
                await submit.click()
                logger.info("Inline letter submitted for %s", vacancy_url)
                return True
            logger.warning("Inline letter submit button not found on %s", vacancy_url)
    except Exception as exc:
        logger.warning("Inline letter fill error on %s: %s", vacancy_url, exc)
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def apply_to_vacancy(page, vacancy_url: str, cover_letter: str = "") -> ApplyResult:
    """Navigate to vacancy page and submit application.

    HH uses two paths after clicking apply:
      Path B (inline/quick-apply): INLINE_LETTER_FORM + RESPONSE_TOPIC_LINK appear.
        The inline form IS the cover letter sent to the employer chat.
        Filling it replaces the need for a separate "go to chat" step.
      Path A (popup): SUBMIT_BUTTON appears inside a modal dialog.

    Timeout handling (30 s): diagnoses the page HTML to determine what actually
    happened (already applied, external apply, questionnaire, etc.) and maps to
    the appropriate status without saving spurious FAILED records.

    Args:
        page:          Playwright Page (already has auth storage state loaded).
        vacancy_url:   Full URL of the HH.ru vacancy (https://hh.ru/vacancy/{id}).
        cover_letter:  Cover letter text to insert (may be empty).

    Returns:
        ApplyResult with status and optional error / artifact paths.
    """
    apply_url = vacancy_url

    try:
        logger.info("Navigating to vacancy: %s", vacancy_url)
        await page.goto(vacancy_url, wait_until="domcontentloaded", timeout=30_000)

        # Accept cookies banner early — may block subsequent interactions
        await _accept_cookies(page)

        # --- Session check ---
        if await _is_session_expired(page):
            logger.warning("Session expired — cannot apply")
            return ApplyResult(status=ApplyStatus.SESSION_EXPIRED, apply_url=apply_url)

        # --- Captcha check before clicking ---
        if await _is_captcha_present(page):
            logger.warning("Captcha detected on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # --- Pre-click: already applied? ---
        try:
            already = await page.wait_for_selector(
                selectors.ALREADY_APPLIED, timeout=_QUICK_TIMEOUT_MS
            )
            if already and await already.is_visible():
                logger.info("Already applied (pre-click) to %s", vacancy_url)
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass

        # Also check chat link (stronger already-applied indicator)
        try:
            chat_link = await page.query_selector(selectors.RESPONSE_TOPIC_LINK)
            if chat_link and await chat_link.is_visible():
                logger.info("Response topic link found pre-click on %s — already applied", vacancy_url)
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass

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
        # Covers both Path A (popup) and Path B (inline/quick-apply).
        try:
            await page.wait_for_selector(_POST_CLICK_OUTCOMES, timeout=_OUTCOME_TIMEOUT_MS)
        except Exception:
            # Timeout — diagnose what happened from the page HTML.
            detected, page_title = await _diagnose_timeout(page)
            logger.info(
                "Post-click timeout on %s — detected_outcome=%s title=%r",
                vacancy_url, detected, page_title,
            )

            # Recoverable: inline form appeared but we missed it (race condition)
            if detected == _DIAGNOSTIC_INLINE:
                logger.info("Late detection: inline letter form on %s", vacancy_url)
                if cover_letter:
                    filled = await _fill_inline_letter(page, cover_letter, vacancy_url)
                    return ApplyResult(
                        status=ApplyStatus.DONE if filled else ApplyStatus.DONE_WITHOUT_LETTER,
                        apply_url=apply_url,
                    )
                return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)

            # Recoverable: already applied (chat exists)
            if detected == _DIAGNOSTIC_CHAT:
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)

            # Manual required: needs human (external / questionnaire / phone)
            if detected in (_DIAGNOSTIC_EXTERNAL, _DIAGNOSTIC_QUESTIONNAIRE, _DIAGNOSTIC_PHONE):
                error = (
                    f"detected_outcome={detected}; "
                    f"page_url={vacancy_url}; "
                    f"page_title={page_title[:100]}"
                )
                return ApplyResult(
                    status=ApplyStatus.MANUAL_REQUIRED,
                    error=error[:500],
                    apply_url=apply_url,
                )

            # Captcha appeared
            if await _is_captcha_present(page):
                return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

            # Unknown — save artifacts and fail
            artifact_suffix = await _save_fail_artifacts(page, vacancy_url)
            error = (
                f"Timeout {_OUTCOME_TIMEOUT_MS // 1000}s; "
                f"detected_outcome={detected}; "
                f"page_url={vacancy_url}; "
                f"page_title={page_title[:80]}"
                f"{artifact_suffix}"
            )
            logger.warning("Apply flow timeout FAILED on %s: %s", vacancy_url, error)
            return ApplyResult(status=ApplyStatus.FAILED, error=error[:500], apply_url=apply_url)

        # --- Outcome arrived — identify which one ---

        # Captcha post-click
        if await _is_captcha_present(page):
            logger.warning("Captcha appeared after click on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # Path B: check inline letter form (quick-apply succeeded)
        # The form appears together with or shortly after RESPONSE_TOPIC_LINK.
        inline_form = None
        try:
            inline_form = await page.query_selector(selectors.INLINE_LETTER_FORM)
        except Exception:
            pass

        if inline_form and await inline_form.is_visible():
            logger.info("Path B (inline): cover letter form detected on %s", vacancy_url)
            if cover_letter:
                filled = await _fill_inline_letter(page, cover_letter, vacancy_url)
                return ApplyResult(
                    status=ApplyStatus.DONE if filled else ApplyStatus.DONE_WITHOUT_LETTER,
                    apply_url=apply_url,
                )
            # No cover letter requested — apply succeeded without letter
            return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)

        # Chat link without inline form: already applied from before (no letter form offered)
        try:
            chat_link = await page.query_selector(selectors.RESPONSE_TOPIC_LINK)
            if chat_link and await chat_link.is_visible():
                logger.info(
                    "Path B (inline, no letter form): quick apply succeeded on %s", vacancy_url
                )
                if cover_letter:
                    logger.warning(
                        "no_cover_letter_field: no inline form on %s — submitted without letter",
                        vacancy_url,
                    )
                    return ApplyResult(
                        status=ApplyStatus.DONE_WITHOUT_LETTER, apply_url=apply_url
                    )
                return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)
        except Exception:
            pass

        # Success toast (fast success path — no form)
        try:
            toast = await page.query_selector(selectors.SUCCESS_TOAST)
            if toast and await toast.is_visible():
                logger.info("Success toast detected on %s (quick apply)", vacancy_url)
                if cover_letter:
                    logger.warning(
                        "no_cover_letter_field: success toast path on %s — submitted without letter",
                        vacancy_url,
                    )
                    return ApplyResult(
                        status=ApplyStatus.DONE_WITHOUT_LETTER, apply_url=apply_url
                    )
                return ApplyResult(status=ApplyStatus.DONE, apply_url=apply_url)
        except Exception:
            pass

        # Response-sent label
        try:
            sent = await page.query_selector(selectors.RESPONSE_SENT_LABEL)
            if sent and await sent.is_visible():
                logger.info("Response-sent label on %s", vacancy_url)
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

        # Path A: popup submit button visible
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

        # --- Path A: fill popup cover letter textarea and submit ---
        letter_filled = False
        try:
            textarea = await page.query_selector(selectors.COVER_LETTER_TEXTAREA)
            if textarea and await textarea.is_visible():
                if cover_letter:
                    await textarea.fill(cover_letter)
                    value = await textarea.input_value()
                    if value:
                        letter_filled = True
                        logger.info("Popup cover letter filled (%d chars)", len(value))
                    else:
                        logger.warning(
                            "Popup letter fill may have failed — value empty on %s", vacancy_url
                        )
                else:
                    logger.debug("Popup textarea present but no letter text provided")
            else:
                if cover_letter:
                    logger.warning(
                        "no_cover_letter_field: popup has no visible textarea on %s — "
                        "submitting without letter",
                        vacancy_url,
                    )
        except Exception as exc:
            logger.warning("Popup cover letter fill error on %s: %s", vacancy_url, exc)

        # Submit
        await submit_btn.click()
        logger.info("Application submitted via popup for %s", vacancy_url)

        # Final captcha check
        if await _is_captcha_present(page):
            logger.warning("Captcha after submit on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

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
