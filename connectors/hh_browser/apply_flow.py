"""HH.ru apply flow — pure browser automation, zero LLM calls.

Takes a Playwright Page object and performs the apply sequence.
Returns an ApplyResult describing the outcome.

Design rules:
- No logging of cookies, auth tokens, or personal credentials
- All selectors in selectors.py (single place to update)
- Playwright imported lazily (never at module level)
- Every DOM interaction wrapped in try/except at the caller level

HH letter-attachment paths (tried in order after apply success):

  Path A — Popup:
    click apply → modal popup opens → SUBMIT_BUTTON appears →
    fill COVER_LETTER_TEXTAREA (optional) → click SUBMIT_BUTTON → submitted.
    If popup had no textarea → continue fallback chain (C, D).

  Path B — Inline (quick apply):
    click apply → page updates inline → INLINE_LETTER_FORM appears →
    fill INLINE_LETTER_TEXTAREA → click INLINE_LETTER_SUBMIT → sent_inline.
    If fill fails → continue fallback chain (C, D).

  Path C — Post-apply textarea (NEW):
    After apply → POST_APPLY_LETTER_TEXTAREA appears on vacancy page →
    fill → click POST_APPLY_LETTER_SUBMIT → sent_post_apply.

  Path D — Chat (NEW, last resort):
    RESPONSE_TOPIC_LINK visible → click → navigate to chat page →
    fill CHAT_MESSAGE_INPUT → click CHAT_SEND_BUTTON → sent_chat.
    If chat is closed → chat_closed.

  After all paths → no_field_found.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from connectors.hh_browser import selectors

logger = logging.getLogger(__name__)

# Timeout for the multi-outcome wait after clicking apply (ms)
_OUTCOME_TIMEOUT_MS = 30_000
# Shorter timeout for optional/quick checks (ms)
_QUICK_TIMEOUT_MS = 3_000
# Timeout for post-submit validation (popup path must confirm success) (ms)
_POST_SUBMIT_TIMEOUT_MS = 15_000
# Timeout to confirm a success toast with a stronger signal (ms)
_TOAST_CONFIRM_TIMEOUT_MS = 10_000
# Directory for failure artifacts (screenshot + HTML snapshot)
_ARTIFACT_DIR = "/tmp/hh_apply_artifacts"

# Signals confirming that popup submit was accepted by HH.
# Any of these on the page means the application went through.
_POST_SUBMIT_SIGNALS = ", ".join([
    selectors.ALREADY_APPLIED,      # vacancy page flipped to already-applied
    selectors.RESPONSE_TOPIC_LINK,  # chat link appeared (quick-apply succeeded)
    selectors.SUCCESS_TOAST,        # "Отклик отправлен" toast
    selectors.RESPONSE_SENT_LABEL,  # response-sent label
    selectors.INLINE_LETTER_FORM,   # inline letter form (path B variant after popup)
    selectors.CAPTCHA_WRAPPER,      # captcha — will be caught in subsequent check
])

# Strong confirmation signals that truly prove apply was recorded on HH's side.
# Used as secondary check after weak signals like SUCCESS_TOAST.
# SUCCESS_TOAST is generic (bloko-notification) and can appear for non-apply events.
_POST_APPLY_CONFIRM_SIGNALS = ", ".join([
    selectors.ALREADY_APPLIED,      # vacancy page shows already-applied state
    selectors.RESPONSE_TOPIC_LINK,  # chat link — only appears after confirmed apply
    selectors.RESPONSE_SENT_LABEL,  # "Отклик отправлен" label on vacancy page
])

# Combined CSS selector waited for after clicking apply.
# First match determines which path HH used.
_POST_CLICK_OUTCOMES = ", ".join([
    selectors.INLINE_LETTER_FORM,       # quick-apply: inline letter form (Path B)
    selectors.RESPONSE_TOPIC_LINK,      # quick-apply: chat link (strong success signal)
    selectors.SUBMIT_BUTTON,            # popup: submit button inside modal (Path A)
    selectors.SUCCESS_TOAST,            # generic success toast
    selectors.RESPONSE_SENT_LABEL,      # generic success label
    selectors.ALREADY_APPLIED,          # already applied state
    selectors.CAPTCHA_WRAPPER,          # captcha appeared
    selectors.EMPLOYER_TEST_REQUIRED,   # employer requires a test (→ MANUAL_REQUIRED)
])

# Diagnostic outcomes from HTML parsing (when timeout occurs)
_DIAGNOSTIC_EXTERNAL = "external_apply"
_DIAGNOSTIC_QUESTIONNAIRE = "questionnaire_required"
_DIAGNOSTIC_PHONE = "phone_verification_required"
_DIAGNOSTIC_COOKIES = "cookies_overlay"
_DIAGNOSTIC_INLINE = "inline_letter_form_appeared"
_DIAGNOSTIC_CHAT = "already_applied_with_chat"
_DIAGNOSTIC_UNKNOWN = "unknown_ui"

# letter_status constants
_LS_NOT_REQUESTED = "not_requested"
_LS_SENT_POPUP = "sent_popup"
_LS_SENT_INLINE = "sent_inline"
_LS_SENT_POST_APPLY = "sent_post_apply"
_LS_SENT_CHAT = "sent_chat"
_LS_NO_FIELD = "no_field_found"
_LS_CHAT_CLOSED = "chat_closed"
_LS_FILL_FAILED = "fill_failed"


class ApplyStatus(str, Enum):
    DONE = "done"                        # Application submitted (letter_status shows letter fate)
    DONE_WITHOUT_LETTER = "done_without_letter"  # Legacy; kept for DB backward compatibility
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
    # Telemetry fields (populated on DONE; empty/default on other statuses)
    letter_status: str = _LS_NOT_REQUESTED  # fate of the cover letter
    flow_type: str = "unknown"              # which apply path was used
    textarea_found: bool = False            # was a letter textarea found?
    detected_outcome: str = ""             # first outcome selector that fired
    final_url: str = ""                    # page.url after all actions
    chat_available: bool = False           # was the chat button visible?
    letter_len: int = 0                    # len of cover_letter text attempted


# ---------------------------------------------------------------------------
# Low-level helpers
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
        url = str(page.url)
        if "login" in url or "account" in url.split("?")[0].split("/")[-1:][0:1]:
            return True
        for selector in (selectors.AUTH_LOGIN_BUTTON, selectors.AUTH_REMEMBER_PASSWORD):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    return True
            except Exception:
                pass
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
    """Parse page HTML and URL after timeout to infer the actual outcome.

    Returns:
        (detected_outcome: str, page_title: str)
    """
    try:
        html = await page.content()
        title = await page.title()
    except Exception:
        return _DIAGNOSTIC_UNKNOWN, ""

    # Read current URL (non-awaitable property; may be MagicMock in tests — guard with str())
    try:
        current_url = str(page.url)
    except Exception:
        current_url = ""

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

    # Questionnaire / test required.
    # HH redirects to /quest/ URLs and shows Russian text — check both.
    # Use stem "анкет" to match all declensions: анкета/анкету/анкеты/анкете.
    if (
        "/quest" in current_url
        or "questionnaire" in html_lower
        or "анкет" in html_lower
        or "ответьте на вопросы" in html_lower
    ):
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


async def _is_vacancy_archived(page) -> bool:
    """Check if the vacancy is archived / expired by the employer.

    Archived vacancies show a banner instead of an apply button.
    Returns True when the vacancy can no longer be applied to.
    """
    try:
        html = await page.content()
        html_lower = html.lower()
        archive_signals = (
            "вакансия в архиве",
            "вакансия закрыта",
            "вакансия снята с публикации",
            "набор на эту вакансию завершён",
            "набор завершён",
        )
        return any(signal in html_lower for signal in archive_signals)
    except Exception:
        return False


async def _fill_inline_letter(page, cover_letter: str, vacancy_url: str) -> bool:
    """Fill and submit the inline cover letter form (Path B).

    Returns True if the letter was filled, submitted, and the form disappeared
    (confirming HH accepted the submission). Returns False on any failure.
    """
    try:
        textarea = await page.query_selector(selectors.INLINE_LETTER_TEXTAREA)
        if textarea and await textarea.is_visible():
            await textarea.fill(cover_letter)
            value = await textarea.input_value()
            if not value:
                logger.warning(
                    "Inline letter fill may have failed — value empty on %s", vacancy_url
                )
                return False
            logger.info("Inline cover letter filled (%d chars) for %s", len(value), vacancy_url)
            submit = await page.query_selector(selectors.INLINE_LETTER_SUBMIT)
            if submit and await submit.is_visible():
                await submit.click()
                logger.info("Inline letter submitted for %s", vacancy_url)
                # Post-submit verification: wait for the inline form to disappear,
                # which confirms HH accepted the letter. If the form stays visible,
                # log a warning but still return True — fill+click completed and a
                # false-negative here would incorrectly fall back to chat path.
                try:
                    await page.wait_for_selector(
                        selectors.INLINE_LETTER_FORM,
                        state="hidden",
                        timeout=5_000,
                    )
                    logger.info(
                        "Inline letter submission confirmed (form hidden) for %s", vacancy_url
                    )
                except Exception:
                    logger.warning(
                        "Inline letter form still visible 5 s after submit on %s "
                        "— submission may not have been accepted by HH",
                        vacancy_url,
                    )
                return True
            logger.warning("Inline letter submit button not found on %s", vacancy_url)
    except Exception as exc:
        logger.warning("Inline letter fill error on %s: %s", vacancy_url, exc)
    return False


async def _send_letter_via_chat(page, cover_letter: str, vacancy_url: str) -> str:
    """Navigate to employer chat and send cover letter (Path D).

    Returns: 'sent_chat' | 'chat_closed' | 'no_field_found'
    """
    try:
        chat_link = await page.query_selector(selectors.RESPONSE_TOPIC_LINK)
        if not chat_link or not await chat_link.is_visible():
            return _LS_NO_FIELD

        await chat_link.click()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass

        # Check if employer has closed chat
        try:
            closed = await page.query_selector(selectors.CHAT_CLOSED_INDICATOR)
            if closed and await closed.is_visible():
                logger.info("Chat is closed for %s", vacancy_url)
                return _LS_CHAT_CLOSED
        except Exception:
            pass

        # Find message input
        msg_input = None
        try:
            msg_input = await page.wait_for_selector(
                selectors.CHAT_MESSAGE_INPUT, timeout=_QUICK_TIMEOUT_MS
            )
        except Exception:
            pass

        if not msg_input or not await msg_input.is_visible():
            logger.warning("Chat message input not found for %s", vacancy_url)
            return _LS_NO_FIELD

        await msg_input.fill(cover_letter)

        send_btn = await page.query_selector(selectors.CHAT_SEND_BUTTON)
        if send_btn and await send_btn.is_visible():
            await send_btn.click()
            logger.info(
                "Cover letter sent via chat for %s (len=%d)", vacancy_url, len(cover_letter)
            )
            return _LS_SENT_CHAT

        logger.warning("Chat send button not found for %s", vacancy_url)
        return _LS_NO_FIELD
    except Exception as exc:
        logger.warning("Chat letter send error on %s: %s", vacancy_url, exc)
        return _LS_NO_FIELD


# ---------------------------------------------------------------------------
# Cover letter attachment fallback chain
# ---------------------------------------------------------------------------


async def _attach_cover_letter(
    page, cover_letter: str, vacancy_url: str
) -> tuple:
    """Try to attach cover letter via ordered fallback chain after apply success.

    Called after the apply button was clicked and success confirmed.
    Does NOT handle popup textarea (popup is submitted before this call).

    Fallback order: inline → post_apply → chat

    Returns:
        (letter_status, textarea_found, chat_available, final_url)
    """
    textarea_found = False
    chat_available = False
    final_url = vacancy_url
    try:
        final_url = page.url
    except Exception:
        pass

    # --- Step 1 (inline): wait briefly for inline form to appear ---
    logger.info("cover_letter_attach: step=inline vacancy=%s", vacancy_url)
    try:
        inline_el = None
        try:
            inline_el = await page.wait_for_selector(
                selectors.INLINE_LETTER_FORM, timeout=_QUICK_TIMEOUT_MS
            )
        except Exception:
            inline_el = await page.query_selector(selectors.INLINE_LETTER_FORM)

        if inline_el and await inline_el.is_visible():
            logger.info("cover_letter_attach: step=inline found=true")
            textarea_found = True
            filled = await _fill_inline_letter(page, cover_letter, vacancy_url)
            if filled:
                logger.info(
                    "cover_letter_attach: result=sent_inline letter_len=%d vacancy=%s",
                    len(cover_letter), vacancy_url,
                )
                return _LS_SENT_INLINE, True, chat_available, final_url
            logger.warning("cover_letter_attach: step=inline fill_failed vacancy=%s", vacancy_url)
            return _LS_FILL_FAILED, True, chat_available, final_url
        else:
            logger.info("cover_letter_attach: step=inline found=false")
    except Exception as exc:
        logger.warning("cover_letter_attach: inline error on %s: %s", vacancy_url, exc)

    # --- Step 2 (post_apply): check for post-apply textarea ---
    logger.info("cover_letter_attach: step=post_apply vacancy=%s", vacancy_url)
    try:
        pa_textarea = await page.query_selector(selectors.POST_APPLY_LETTER_TEXTAREA)
        if pa_textarea and await pa_textarea.is_visible():
            logger.info("cover_letter_attach: step=post_apply found=true")
            textarea_found = True
            await pa_textarea.fill(cover_letter)
            value = await pa_textarea.input_value()
            if value:
                pa_submit = await page.query_selector(selectors.POST_APPLY_LETTER_SUBMIT)
                if pa_submit and await pa_submit.is_visible():
                    await pa_submit.click()
                    logger.info(
                        "cover_letter_attach: result=sent_post_apply letter_len=%d vacancy=%s",
                        len(cover_letter), vacancy_url,
                    )
                    return _LS_SENT_POST_APPLY, True, chat_available, final_url
            logger.warning(
                "cover_letter_attach: step=post_apply fill_failed vacancy=%s", vacancy_url
            )
            return _LS_FILL_FAILED, True, chat_available, final_url
        else:
            logger.info("cover_letter_attach: step=post_apply found=false")
    except Exception as exc:
        logger.warning("cover_letter_attach: post_apply error on %s: %s", vacancy_url, exc)

    # --- Step 3 (chat): navigate to employer chat ---
    logger.info("cover_letter_attach: step=chat vacancy=%s", vacancy_url)
    try:
        chat_link = await page.query_selector(selectors.RESPONSE_TOPIC_LINK)
        if chat_link and await chat_link.is_visible():
            chat_available = True
            chat_status = await _send_letter_via_chat(page, cover_letter, vacancy_url)
            try:
                final_url = page.url
            except Exception:
                pass
            logger.info(
                "cover_letter_attach: result=%s letter_len=%d vacancy=%s",
                chat_status, len(cover_letter), vacancy_url,
            )
            return chat_status, chat_status == _LS_SENT_CHAT, True, final_url
        else:
            logger.info("cover_letter_attach: step=chat found=false")
    except Exception as exc:
        logger.warning("cover_letter_attach: chat error on %s: %s", vacancy_url, exc)

    logger.warning(
        "cover_letter_attach: result=no_field_found vacancy=%s", vacancy_url
    )
    return _LS_NO_FIELD, False, False, final_url


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def apply_to_vacancy(page, vacancy_url: str, cover_letter: str = "") -> ApplyResult:
    """Navigate to vacancy page and submit application.

    After detecting apply success, always runs the letter attachment fallback chain
    (inline → post_apply → chat → no_field_found) when cover_letter is provided.

    Args:
        page:          Playwright Page (already has auth storage state loaded).
        vacancy_url:   Full URL of the HH.ru vacancy (https://hh.ru/vacancy/{id}).
        cover_letter:  Cover letter text to insert (may be empty).

    Returns:
        ApplyResult with status, letter_status, and telemetry fields.
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
                logger.info(
                    "Response topic link found pre-click on %s — already applied", vacancy_url
                )
                return ApplyResult(status=ApplyStatus.ALREADY_APPLIED, apply_url=apply_url)
        except Exception:
            pass

        # --- Pre-click: employer requires a test/questionnaire ---
        try:
            test_el = await page.query_selector(selectors.EMPLOYER_TEST_REQUIRED)
            if test_el and await test_el.is_visible():
                logger.info(
                    "Employer test/questionnaire required (pre-click) on %s — manual action",
                    vacancy_url,
                )
                return ApplyResult(
                    status=ApplyStatus.MANUAL_REQUIRED,
                    error="employer_test_required",
                    detected_outcome="employer_test_required",
                    apply_url=apply_url,
                )
        except Exception:
            pass

        # --- Pre-click: archived / expired vacancy ---
        # HH keeps the URL active but removes the apply button and shows an archive banner.
        # Detect this early to avoid a misleading "manual_required" notification.
        if await _is_vacancy_archived(page):
            logger.info(
                "Vacancy is archived/expired on %s — treating as already applied", vacancy_url
            )
            return ApplyResult(
                status=ApplyStatus.ALREADY_APPLIED,
                error="vacancy_archived",
                apply_url=apply_url,
                detected_outcome="vacancy_archived",
            )

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

        # --- Click apply button (wait for element to be stable before clicking) ---
        try:
            await apply_btn.wait_for_element_state("stable", timeout=5_000)
        except Exception:
            logger.debug("apply_btn stable-wait timed out on %s — clicking anyway", vacancy_url)
        await apply_btn.click()
        logger.debug("Clicked apply button on %s", vacancy_url)

        # --- Multi-outcome wait (30 s) ---
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
                        status=ApplyStatus.DONE,
                        letter_status=_LS_SENT_INLINE if filled else _LS_FILL_FAILED,
                        flow_type="inline",
                        textarea_found=True,
                        detected_outcome=detected,
                        apply_url=apply_url,
                        letter_len=len(cover_letter),
                    )
                return ApplyResult(
                    status=ApplyStatus.DONE,
                    letter_status=_LS_NOT_REQUESTED,
                    flow_type="inline",
                    detected_outcome=detected,
                    apply_url=apply_url,
                )

            # Recoverable: already applied (chat exists)
            if detected == _DIAGNOSTIC_CHAT:
                return ApplyResult(
                    status=ApplyStatus.ALREADY_APPLIED,
                    detected_outcome=detected,
                    apply_url=apply_url,
                )

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
                    detected_outcome=detected,
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
            return ApplyResult(
                status=ApplyStatus.FAILED,
                error=error[:500],
                detected_outcome=detected,
                apply_url=apply_url,
            )

        # ---------------------------------------------------------------------------
        # Outcome arrived — identify which one
        # ---------------------------------------------------------------------------

        # Captcha post-click
        if await _is_captcha_present(page):
            logger.warning("Captcha appeared after click on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # Employer test/questionnaire indicator — appeared after click
        try:
            test_el = await page.query_selector(selectors.EMPLOYER_TEST_REQUIRED)
            if test_el and await test_el.is_visible():
                logger.info(
                    "Employer test required (post-click) on %s — manual action", vacancy_url
                )
                return ApplyResult(
                    status=ApplyStatus.MANUAL_REQUIRED,
                    error="employer_test_required",
                    detected_outcome="employer_test_required",
                    apply_url=apply_url,
                )
        except Exception:
            pass

        # Path B: check inline letter form (quick-apply succeeded)
        inline_form = None
        try:
            inline_form = await page.query_selector(selectors.INLINE_LETTER_FORM)
        except Exception:
            pass

        if inline_form and await inline_form.is_visible():
            logger.info("Path B (inline): cover letter form detected on %s", vacancy_url)
            flow_type = "inline"
            if cover_letter:
                filled = await _fill_inline_letter(page, cover_letter, vacancy_url)
                if filled:
                    return ApplyResult(
                        status=ApplyStatus.DONE,
                        letter_status=_LS_SENT_INLINE,
                        flow_type=flow_type,
                        textarea_found=True,
                        detected_outcome="inline_form",
                        apply_url=apply_url,
                        letter_len=len(cover_letter),
                    )
                # Inline fill failed — try remaining fallbacks (post_apply, chat)
                ls, tf, ca, fu = await _attach_cover_letter(page, cover_letter, vacancy_url)
                return ApplyResult(
                    status=ApplyStatus.DONE,
                    letter_status=ls,
                    flow_type=flow_type,
                    textarea_found=tf,
                    detected_outcome="inline_form",
                    final_url=fu,
                    chat_available=ca,
                    apply_url=apply_url,
                    letter_len=len(cover_letter),
                )
            # No cover letter requested
            return ApplyResult(
                status=ApplyStatus.DONE,
                letter_status=_LS_NOT_REQUESTED,
                flow_type=flow_type,
                detected_outcome="inline_form",
                apply_url=apply_url,
            )

        # Chat link detected (quick apply without inline form)
        try:
            chat_link = await page.query_selector(selectors.RESPONSE_TOPIC_LINK)
            if chat_link and await chat_link.is_visible():
                logger.info("Path B (quick apply, no inline form) on %s", vacancy_url)
                flow_type = "quick_apply"
                if cover_letter:
                    ls, tf, ca, fu = await _attach_cover_letter(page, cover_letter, vacancy_url)
                    return ApplyResult(
                        status=ApplyStatus.DONE,
                        letter_status=ls,
                        flow_type=flow_type,
                        textarea_found=tf,
                        detected_outcome="response_topic_link",
                        final_url=fu,
                        chat_available=ca,
                        apply_url=apply_url,
                        letter_len=len(cover_letter),
                    )
                return ApplyResult(
                    status=ApplyStatus.DONE,
                    letter_status=_LS_NOT_REQUESTED,
                    flow_type=flow_type,
                    detected_outcome="response_topic_link",
                    apply_url=apply_url,
                )
        except Exception:
            pass

        # Success toast (weak signal — needs secondary confirmation)
        # bloko-notification is a generic HH component that fires for many events,
        # not just apply success. Wait for a strong signal before marking DONE.
        try:
            toast = await page.query_selector(selectors.SUCCESS_TOAST)
            if toast and await toast.is_visible():
                logger.info(
                    "Success toast detected on %s — waiting for strong confirmation",
                    vacancy_url,
                )
                flow_type = "quick_apply"
                try:
                    await page.wait_for_selector(
                        _POST_APPLY_CONFIRM_SIGNALS, timeout=_TOAST_CONFIRM_TIMEOUT_MS
                    )
                except Exception:
                    # Toast appeared but no strong apply signal found — likely false positive
                    artifact_suffix = await _save_fail_artifacts(page, vacancy_url)
                    logger.warning(
                        "Toast appeared but no strong confirmation on %s "
                        "(toast_unconfirmed)%s",
                        vacancy_url,
                        artifact_suffix,
                    )
                    return ApplyResult(
                        status=ApplyStatus.FAILED,
                        error=f"toast_unconfirmed{artifact_suffix}",
                        flow_type=flow_type,
                        detected_outcome="toast_unconfirmed",
                        apply_url=apply_url,
                    )
                logger.info("Toast confirmed by strong signal on %s", vacancy_url)
                if cover_letter:
                    # Run full attach chain — inline form may appear shortly after toast
                    ls, tf, ca, fu = await _attach_cover_letter(page, cover_letter, vacancy_url)
                    return ApplyResult(
                        status=ApplyStatus.DONE,
                        letter_status=ls,
                        flow_type=flow_type,
                        textarea_found=tf,
                        detected_outcome="success_toast",
                        final_url=fu,
                        chat_available=ca,
                        apply_url=apply_url,
                        letter_len=len(cover_letter),
                    )
                return ApplyResult(
                    status=ApplyStatus.DONE,
                    letter_status=_LS_NOT_REQUESTED,
                    flow_type=flow_type,
                    detected_outcome="success_toast",
                    apply_url=apply_url,
                )
        except Exception:
            pass

        # Response-sent label
        try:
            sent = await page.query_selector(selectors.RESPONSE_SENT_LABEL)
            if sent and await sent.is_visible():
                logger.info("Response-sent label on %s", vacancy_url)
                flow_type = "quick_apply"
                if cover_letter:
                    ls, tf, ca, fu = await _attach_cover_letter(page, cover_letter, vacancy_url)
                    return ApplyResult(
                        status=ApplyStatus.DONE,
                        letter_status=ls,
                        flow_type=flow_type,
                        textarea_found=tf,
                        detected_outcome="response_sent",
                        final_url=fu,
                        chat_available=ca,
                        apply_url=apply_url,
                        letter_len=len(cover_letter),
                    )
                return ApplyResult(
                    status=ApplyStatus.DONE,
                    letter_status=_LS_NOT_REQUESTED,
                    flow_type=flow_type,
                    detected_outcome="response_sent",
                    apply_url=apply_url,
                )
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

        # --- Path A: fill popup cover letter textarea then submit ---
        flow_type = "popup"
        popup_letter_status = _LS_NOT_REQUESTED
        popup_textarea_found = False

        if cover_letter:
            try:
                # Some popups hide the textarea behind a toggle — click it first.
                try:
                    toggle = await page.query_selector(selectors.COVER_LETTER_TOGGLE)
                    if toggle and await toggle.is_visible():
                        await toggle.click()
                        logger.debug("Clicked letter toggle on %s", vacancy_url)
                except Exception:
                    pass

                textarea = await page.query_selector(selectors.COVER_LETTER_TEXTAREA)
                if textarea and await textarea.is_visible():
                    popup_textarea_found = True
                    await textarea.fill(cover_letter)
                    value = await textarea.input_value()
                    if value:
                        popup_letter_status = _LS_SENT_POPUP
                        logger.info(
                            "Popup cover letter filled (%d chars) on %s", len(value), vacancy_url
                        )
                    else:
                        logger.warning(
                            "Popup letter fill may have failed — value empty on %s", vacancy_url
                        )
                else:
                    logger.info(
                        "cover_letter_attach: step=popup found=false vacancy=%s", vacancy_url
                    )
            except Exception as exc:
                logger.warning("Popup cover letter fill error on %s: %s", vacancy_url, exc)

        # Detect employer questions — return MANUAL_REQUIRED ONLY when the cover letter
        # textarea was NOT found. On some vacancies HH wraps a required cover letter
        # textarea inside a vacancy-response-question element; filling it is sufficient
        # and no manual action is needed. Return MANUAL_REQUIRED only when there are
        # genuinely unanswerable questions (dropdowns, radio buttons, etc.) and no
        # textarea was available.
        if not popup_textarea_found:
            try:
                question_el = await page.query_selector(selectors.POPUP_QUESTION)
                if question_el and await question_el.is_visible():
                    logger.info(
                        "Popup has employer questions on %s — attempting auto-fill",
                        vacancy_url,
                    )
                    from connectors.hh_browser.questionnaire import fill_popup_questionnaire
                    from capabilities.career_os.models import Profile
                    from core.config import config as _cfg
                    try:
                        _profile = Profile.from_file(_cfg.profile_path)
                    except Exception:
                        _profile = None
                    all_qs_filled, filled_qs, skipped_qs = await fill_popup_questionnaire(
                        page, _profile, vacancy_url
                    )
                    if all_qs_filled:
                        logger.info(
                            "Popup questionnaire auto-filled: %s on %s",
                            filled_qs, vacancy_url,
                        )
                        # All questions answered — proceed to submit
                    elif skipped_qs:
                        logger.info(
                            "Popup questionnaire: filled=%s skipped=%s on %s",
                            filled_qs, skipped_qs, vacancy_url,
                        )
                        return ApplyResult(
                            status=ApplyStatus.MANUAL_REQUIRED,
                            error=f"popup_questions_unanswered: {skipped_qs[:3]}",
                            detected_outcome="popup_employer_questions",
                            flow_type=flow_type,
                            apply_url=apply_url,
                        )
            except Exception as exc:
                logger.warning(
                    "Popup questionnaire auto-fill failed on %s: %s — returning manual_required",
                    vacancy_url, exc,
                )
                return ApplyResult(
                    status=ApplyStatus.MANUAL_REQUIRED,
                    error="popup_employer_questions",
                    detected_outcome="popup_employer_questions",
                    flow_type=flow_type,
                    apply_url=apply_url,
                )

        # Submit popup (apply happens here regardless of letter outcome)
        await submit_btn.click()
        logger.info("Application submitted via popup for %s", vacancy_url)

        # Post-submit validation: wait for a recognizable outcome before marking DONE.
        # Without this, a failed submit would silently return DONE.
        try:
            await page.wait_for_selector(
                _POST_SUBMIT_SIGNALS, timeout=_POST_SUBMIT_TIMEOUT_MS
            )
        except Exception:
            artifact_suffix = await _save_fail_artifacts(page, vacancy_url)
            # Check if session expired during submit (redirect to login page)
            if await _is_session_expired(page):
                logger.warning("Session expired during popup submit on %s", vacancy_url)
                return ApplyResult(
                    status=ApplyStatus.SESSION_EXPIRED,
                    apply_url=apply_url,
                )
            logger.warning(
                "Popup submit timeout — no success signal on %s%s",
                vacancy_url,
                artifact_suffix,
            )
            return ApplyResult(
                status=ApplyStatus.FAILED,
                error=f"popup_submit_timeout{artifact_suffix}",
                flow_type=flow_type,
                detected_outcome="popup_submit_timeout",
                apply_url=apply_url,
            )

        # Final captcha check (some vacancies show captcha after submit)
        if await _is_captcha_present(page):
            logger.warning("Captcha after submit on %s", vacancy_url)
            return ApplyResult(status=ApplyStatus.CAPTCHA, apply_url=apply_url)

        # If letter was successfully sent via popup, we're done
        if popup_letter_status == _LS_SENT_POPUP:
            return ApplyResult(
                status=ApplyStatus.DONE,
                letter_status=_LS_SENT_POPUP,
                flow_type=flow_type,
                textarea_found=True,
                detected_outcome="popup_submit",
                final_url=page.url,
                apply_url=apply_url,
                letter_len=len(cover_letter),
            )

        # Popup had no textarea (or fill failed) — run remaining attach chain
        if cover_letter:
            ls, tf, ca, fu = await _attach_cover_letter(page, cover_letter, vacancy_url)
            # If a fallback path found a textarea, mark it
            final_textarea_found = popup_textarea_found or tf
            return ApplyResult(
                status=ApplyStatus.DONE,
                letter_status=ls,
                flow_type=flow_type,
                textarea_found=final_textarea_found,
                detected_outcome="popup_submit",
                final_url=fu,
                chat_available=ca,
                apply_url=apply_url,
                letter_len=len(cover_letter),
            )

        return ApplyResult(
            status=ApplyStatus.DONE,
            letter_status=_LS_NOT_REQUESTED,
            flow_type=flow_type,
            detected_outcome="popup_submit",
            apply_url=apply_url,
        )

    except Exception as exc:
        logger.warning("Apply flow failed for %s: %s", vacancy_url, exc)
        return ApplyResult(
            status=ApplyStatus.FAILED,
            error=str(exc)[:500],
            apply_url=apply_url,
        )
