"""Tests for connectors/hh_browser/apply_flow.py.

All Playwright page interactions are mocked — no real browser required.
Covers: DONE, DONE_WITHOUT_LETTER, ALREADY_APPLIED, MANUAL_REQUIRED,
CAPTCHA, SESSION_EXPIRED, FAILED, multi-outcome wait, artifact saving,
Path B (inline letter form), cookies dismissal, timeout diagnostics.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from connectors.hh_browser.apply_flow import (
    ApplyResult,
    ApplyStatus,
    apply_to_vacancy,
    _is_captcha_present,
    _is_session_expired,
    _accept_cookies,
    _diagnose_timeout,
    _fill_inline_letter,
    _POST_CLICK_OUTCOMES,
    _DIAGNOSTIC_INLINE,
    _DIAGNOSTIC_CHAT,
    _DIAGNOSTIC_EXTERNAL,
    _DIAGNOSTIC_QUESTIONNAIRE,
    _DIAGNOSTIC_PHONE,
    _DIAGNOSTIC_COOKIES,
    _DIAGNOSTIC_UNKNOWN,
)


# ---------------------------------------------------------------------------
# ApplyStatus enum
# ---------------------------------------------------------------------------


class TestApplyStatus:
    def test_done_value(self):
        assert ApplyStatus.DONE == "done"

    def test_done_without_letter_value(self):
        assert ApplyStatus.DONE_WITHOUT_LETTER == "done_without_letter"

    def test_captcha_value(self):
        assert ApplyStatus.CAPTCHA == "captcha"

    def test_session_expired_value(self):
        assert ApplyStatus.SESSION_EXPIRED == "session_expired"

    def test_manual_required_value(self):
        assert ApplyStatus.MANUAL_REQUIRED == "manual_required"

    def test_already_applied_value(self):
        assert ApplyStatus.ALREADY_APPLIED == "already_applied"

    def test_failed_value(self):
        assert ApplyStatus.FAILED == "failed"


# ---------------------------------------------------------------------------
# _is_captcha_present
# ---------------------------------------------------------------------------


class TestIsCaptchaPresent:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_elements(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await _is_captcha_present(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_element_visible(self):
        mock_el = AsyncMock()
        mock_el.is_visible = AsyncMock(return_value=True)
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=mock_el)
        result = await _is_captcha_present(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_element_hidden(self):
        mock_el = AsyncMock()
        mock_el.is_visible = AsyncMock(return_value=False)
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=mock_el)
        result = await _is_captcha_present(page)
        assert result is False


# ---------------------------------------------------------------------------
# _is_session_expired
# ---------------------------------------------------------------------------


class TestIsSessionExpired:
    @pytest.mark.asyncio
    async def test_returns_true_when_login_in_url(self):
        page = AsyncMock()
        page.url = "https://hh.ru/login?backurl=/vacancy/123"
        page.query_selector = AsyncMock(return_value=None)
        result = await _is_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_vacancy_page(self):
        page = AsyncMock()
        page.url = "https://hh.ru/vacancy/123456"
        page.query_selector = AsyncMock(return_value=None)
        result = await _is_session_expired(page)
        assert result is False


# ---------------------------------------------------------------------------
# _accept_cookies
# ---------------------------------------------------------------------------


class TestAcceptCookies:
    @pytest.mark.asyncio
    async def test_clicks_when_visible(self):
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=True)
        btn.click = AsyncMock()

        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=btn)

        await _accept_cookies(page)
        btn.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_click_when_not_visible(self):
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=False)
        btn.click = AsyncMock()

        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=btn)

        await _accept_cookies(page)
        btn.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_click_when_absent(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        # should not raise
        await _accept_cookies(page)


# ---------------------------------------------------------------------------
# _diagnose_timeout
# ---------------------------------------------------------------------------


class TestDiagnoseTimeout:
    @pytest.mark.asyncio
    async def test_detects_inline_form_and_chat(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html><div data-qa='vacancy-response-letter-informer'></div>"
            "<a data-qa='vacancy-response-link-view-topic'>Чат</a></html>"
        ))
        page.title = AsyncMock(return_value="Менеджер по продажам")

        outcome, title = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_INLINE
        assert title == "Менеджер по продажам"

    @pytest.mark.asyncio
    async def test_detects_chat_without_form(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html><a data-qa='vacancy-response-link-view-topic'>Чат</a></html>"
        ))
        page.title = AsyncMock(return_value="Вакансия")

        outcome, title = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_CHAT

    @pytest.mark.asyncio
    async def test_detects_inline_form_alone(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html><div data-qa='vacancy-response-letter-informer'></div></html>"
        ))
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_INLINE

    @pytest.mark.asyncio
    async def test_detects_external_apply(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html>Перейти на сайт работодателя</html>"
        ))
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_EXTERNAL

    @pytest.mark.asyncio
    async def test_detects_questionnaire(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html>questionnaire required</html>")
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_QUESTIONNAIRE

    @pytest.mark.asyncio
    async def test_detects_phone_verification(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html>Подтвердить телефон</html>")
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_PHONE

    @pytest.mark.asyncio
    async def test_detects_cookies_overlay(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html><button data-qa='cookies-policy-informer-accept'>OK</button></html>"
        ))
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_COOKIES

    @pytest.mark.asyncio
    async def test_returns_unknown_for_unrecognised(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html><p>Something new</p></html>")
        page.title = AsyncMock(return_value="")

        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_UNKNOWN

    @pytest.mark.asyncio
    async def test_handles_page_error_gracefully(self):
        page = AsyncMock()
        page.content = AsyncMock(side_effect=Exception("page crashed"))
        page.title = AsyncMock(side_effect=Exception("page crashed"))

        outcome, title = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_UNKNOWN
        assert title == ""


# ---------------------------------------------------------------------------
# _fill_inline_letter
# ---------------------------------------------------------------------------


class TestFillInlineLetter:
    @pytest.mark.asyncio
    async def test_returns_true_when_filled_and_submitted(self):
        textarea = AsyncMock()
        textarea.is_visible = AsyncMock(return_value=True)
        textarea.fill = AsyncMock()
        textarea.input_value = AsyncMock(return_value="Мое письмо")

        submit = AsyncMock()
        submit.is_visible = AsyncMock(return_value=True)
        submit.click = AsyncMock()

        from connectors.hh_browser import selectors as sel

        async def qs(selector):
            if selector == sel.INLINE_LETTER_TEXTAREA:
                return textarea
            if selector == sel.INLINE_LETTER_SUBMIT:
                return submit
            return None

        page = AsyncMock()
        page.query_selector = qs

        result = await _fill_inline_letter(page, "Мое письмо", "https://hh.ru/vacancy/1")
        assert result is True
        textarea.fill.assert_called_once_with("Мое письмо")
        submit.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_textarea_absent(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        result = await _fill_inline_letter(page, "Письмо", "https://hh.ru/vacancy/1")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_fill_leaves_empty_value(self):
        textarea = AsyncMock()
        textarea.is_visible = AsyncMock(return_value=True)
        textarea.fill = AsyncMock()
        textarea.input_value = AsyncMock(return_value="")  # fill silently failed

        from connectors.hh_browser import selectors as sel

        async def qs(selector):
            if selector == sel.INLINE_LETTER_TEXTAREA:
                return textarea
            return None

        page = AsyncMock()
        page.query_selector = qs

        result = await _fill_inline_letter(page, "Письмо", "https://hh.ru/vacancy/1")
        assert result is False


# ---------------------------------------------------------------------------
# apply_to_vacancy — mock factory
# ---------------------------------------------------------------------------


def _make_page(
    url="https://hh.ru/vacancy/111",
    captcha_visible=False,
    already_applied=False,
    apply_btn_found=True,
    # Post-click outcomes
    outcome_timeout=False,      # True → wait_for_selector(_POST_CLICK_OUTCOMES) raises
    success_toast=False,        # True → SUCCESS_TOAST query_selector returns visible element
    submit_popup=True,          # True → SUBMIT_BUTTON query_selector returns visible element
    textarea_found=False,       # True → COVER_LETTER_TEXTAREA query_selector returns element
    textarea_fill_value="filled",
    # Path B (inline) params — these appear AFTER clicking apply (stateful)
    inline_form=False,          # True → INLINE_LETTER_FORM visible after click
    inline_textarea=False,      # True → INLINE_LETTER_TEXTAREA visible after click
    inline_submit=True,         # True → INLINE_LETTER_SUBMIT visible after click
    response_topic_link=False,  # True → RESPONSE_TOPIC_LINK visible after click
    # response_topic_preclick: True → RESPONSE_TOPIC_LINK visible BEFORE click (= already applied)
    response_topic_preclick=False,
    # Cookies
    cookies_visible=False,      # True → COOKIES_ACCEPT visible
):
    """Build a mock Playwright page for the multi-outcome apply flow.

    Path B elements (inline_form, response_topic_link) only become visible AFTER
    apply_btn.click() is called, matching real HH behaviour where those elements
    appear as a result of clicking apply.
    """
    from connectors.hh_browser import selectors as sel

    state = {"clicked": False}

    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.screenshot = AsyncMock()
    page.content = AsyncMock(return_value="<html>mock</html>")
    page.title = AsyncMock(return_value="Mock vacancy")

    # --- Element mocks ---
    def _make_el(visible=True):
        el = AsyncMock()
        el.is_visible = AsyncMock(return_value=visible)
        el.click = AsyncMock()
        el.fill = AsyncMock()
        el.input_value = AsyncMock(return_value="filled")
        return el

    captcha_el = _make_el(captcha_visible)
    already_el = _make_el(already_applied)

    apply_btn = _make_el(apply_btn_found)
    # Track click — post-click elements become visible after this
    _original_apply_click = apply_btn.click
    async def _apply_btn_click():
        state["clicked"] = True
        return await _original_apply_click()
    apply_btn.click = _apply_btn_click

    submit_el = _make_el(submit_popup)
    toast_el = _make_el(True)

    textarea_el = _make_el(textarea_found)
    textarea_el.input_value = AsyncMock(return_value=textarea_fill_value if textarea_found else "")

    inline_form_el = _make_el(True)        # is_visible=True when returned
    inline_textarea_el = _make_el(True)
    inline_textarea_el.input_value = AsyncMock(return_value="Письмо" if inline_textarea else "")
    inline_submit_el = _make_el(inline_submit)
    response_topic_el = _make_el(True)
    cookies_btn = _make_el(cookies_visible)

    # --- query_selector ---
    async def mock_query_selector(selector):
        if selector in (sel.CAPTCHA_WRAPPER, sel.RECAPTCHA_IFRAME, sel.SMARTCAPTCHA_IFRAME):
            return captcha_el if captcha_visible else None
        if selector == sel.AUTH_LOGIN_BUTTON:
            return None
        if selector == sel.SUCCESS_TOAST:
            return toast_el if success_toast else None
        if selector == sel.RESPONSE_SENT_LABEL:
            return None
        if selector == sel.ALREADY_APPLIED:
            return already_el if already_applied else None
        if selector == sel.SUBMIT_BUTTON:
            return submit_el if submit_popup else None
        if selector == sel.COVER_LETTER_TEXTAREA:
            return textarea_el if textarea_found else None
        # Path B elements: only visible after click (unless preclick variant)
        if selector == sel.INLINE_LETTER_FORM:
            return inline_form_el if (inline_form and state["clicked"]) else None
        if selector == sel.INLINE_LETTER_TEXTAREA:
            return inline_textarea_el if (inline_textarea and state["clicked"]) else None
        if selector == sel.INLINE_LETTER_SUBMIT:
            return inline_submit_el if (inline_submit and state["clicked"]) else None
        if selector == sel.RESPONSE_TOPIC_LINK:
            if response_topic_preclick:
                return response_topic_el  # visible before AND after click
            return response_topic_el if (response_topic_link and state["clicked"]) else None
        if selector == sel.COOKIES_ACCEPT:
            return cookies_btn if cookies_visible else None
        return None

    page.query_selector = mock_query_selector

    # --- wait_for_selector ---
    async def mock_wait_for_selector(selector, timeout=None):
        if selector == sel.ALREADY_APPLIED:
            if already_applied:
                return already_el
            raise Exception("Timeout — element not found")
        if selector in (sel.APPLY_BUTTON, sel.APPLY_BUTTON_BOTTOM):
            if apply_btn_found:
                return apply_btn
            raise Exception("Timeout — apply button not found")
        if selector == _POST_CLICK_OUTCOMES:
            if outcome_timeout:
                raise Exception("Timeout 30s — no post-click outcome detected")
            return AsyncMock()
        raise Exception(f"Unknown selector: {selector}")

    page.wait_for_selector = mock_wait_for_selector
    return page


# ---------------------------------------------------------------------------
# apply_to_vacancy — full flow
# ---------------------------------------------------------------------------


class TestApplyToVacancy:
    # --- Path A: popup ---

    @pytest.mark.asyncio
    async def test_done_on_success_with_letter(self):
        """Popup opens, textarea present, letter filled → DONE."""
        page = _make_page(textarea_found=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_done_without_letter_when_no_textarea(self):
        """Popup opens but textarea absent, cover_letter provided → DONE_WITHOUT_LETTER."""
        page = _make_page(textarea_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE_WITHOUT_LETTER

    @pytest.mark.asyncio
    async def test_done_when_no_cover_letter_provided(self):
        """No cover letter text → textarea absence doesn't trigger DONE_WITHOUT_LETTER."""
        page = _make_page(textarea_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    # --- Path B: inline (quick-apply) ---

    @pytest.mark.asyncio
    async def test_path_b_done_with_inline_letter(self):
        """Inline form visible + cover letter → fills form → DONE."""
        page = _make_page(
            submit_popup=False,
            inline_form=True,
            inline_textarea=True,
            response_topic_link=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Сопроводительное")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_path_b_done_without_letter_when_no_textarea(self):
        """Inline form present but no textarea visible → DONE_WITHOUT_LETTER."""
        page = _make_page(
            submit_popup=False,
            inline_form=True,
            inline_textarea=False,  # textarea not visible — fill will return False
            response_topic_link=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        # inline_form visible → tries _fill_inline_letter → textarea not visible → False → DONE_WITHOUT_LETTER
        assert result.status == ApplyStatus.DONE_WITHOUT_LETTER

    @pytest.mark.asyncio
    async def test_path_b_done_when_no_cover_letter(self):
        """Inline form + no cover letter requested → DONE."""
        page = _make_page(
            submit_popup=False,
            inline_form=True,
            inline_textarea=True,
            response_topic_link=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_path_b_chat_link_without_inline_form_no_letter(self):
        """Chat link only (no inline form), no letter → DONE."""
        page = _make_page(
            submit_popup=False,
            inline_form=False,
            response_topic_link=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_path_b_chat_link_without_inline_form_with_letter(self):
        """Chat link only (no inline form), cover letter provided → DONE_WITHOUT_LETTER."""
        page = _make_page(
            submit_popup=False,
            inline_form=False,
            response_topic_link=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE_WITHOUT_LETTER

    # --- Success toast ---

    @pytest.mark.asyncio
    async def test_done_when_success_toast_no_letter(self):
        """Success toast appears (quick apply), no cover_letter → DONE."""
        page = _make_page(success_toast=True, submit_popup=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_done_without_letter_when_success_toast_with_letter(self):
        """Success toast + cover_letter provided → DONE_WITHOUT_LETTER."""
        page = _make_page(success_toast=True, submit_popup=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE_WITHOUT_LETTER

    # --- Already applied ---

    @pytest.mark.asyncio
    async def test_already_applied(self):
        page = _make_page(already_applied=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    @pytest.mark.asyncio
    async def test_already_applied_via_response_topic_link_preclick(self):
        """Pre-click check: chat link visible before click → ALREADY_APPLIED."""
        page = _make_page(response_topic_preclick=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    # --- Manual required ---

    @pytest.mark.asyncio
    async def test_manual_required_when_no_apply_button(self):
        page = _make_page(apply_btn_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED

    # --- Captcha ---

    @pytest.mark.asyncio
    async def test_captcha_detected_early(self):
        page = _make_page(captcha_visible=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.CAPTCHA

    # --- Session expired ---

    @pytest.mark.asyncio
    async def test_session_expired_when_login_url(self):
        page = _make_page(url="https://hh.ru/login")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.SESSION_EXPIRED

    # --- goto failure ---

    @pytest.mark.asyncio
    async def test_failed_on_goto_exception(self):
        page = AsyncMock()
        page.url = "https://hh.ru/vacancy/111"
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        page.query_selector = AsyncMock(return_value=None)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.FAILED
        assert "Network error" in result.error

    # --- Timeout + diagnosis ---

    @pytest.mark.asyncio
    async def test_failed_on_outcome_timeout_unknown(self):
        """Unknown timeout → FAILED with artifact paths."""
        page = _make_page(outcome_timeout=True)
        # content returns generic HTML, no recognisable selectors
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.FAILED
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_timeout_with_inline_form_in_html_gives_done(self):
        """Timeout → HTML has inline form → treat as DONE (no letter)."""
        page = _make_page(outcome_timeout=True)
        # Override content to include inline form selector value
        page.content = AsyncMock(return_value=(
            "<html><div data-qa='vacancy-response-letter-informer'></div></html>"
        ))
        page.title = AsyncMock(return_value="Вакансия")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        # No textarea visible in mock, but cover_letter="" → DONE
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_timeout_with_chat_link_in_html_gives_already_applied(self):
        """Timeout → HTML has chat link only → ALREADY_APPLIED."""
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value=(
            "<html><a data-qa='vacancy-response-link-view-topic'>Чат</a></html>"
        ))
        page.title = AsyncMock(return_value="Вакансия")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    @pytest.mark.asyncio
    async def test_timeout_with_external_apply_gives_manual_required(self):
        """Timeout → external apply detected → MANUAL_REQUIRED."""
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value=(
            "<html>Перейти на сайт работодателя</html>"
        ))
        page.title = AsyncMock(return_value="Внешний отклик")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "external_apply" in result.error

    @pytest.mark.asyncio
    async def test_timeout_with_questionnaire_gives_manual_required(self):
        """Timeout → questionnaire → MANUAL_REQUIRED with detected_outcome."""
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value="<html>questionnaire</html>")
        page.title = AsyncMock(return_value="Анкета")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "questionnaire_required" in result.error

    @pytest.mark.asyncio
    async def test_error_format_has_detected_outcome_and_page_url(self):
        """MANUAL_REQUIRED error must include detected_outcome= and page_url=."""
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value="<html>Подтвердить телефон</html>")
        page.title = AsyncMock(return_value="Подтверждение")
        url = "https://hh.ru/vacancy/999"
        result = await apply_to_vacancy(page, url)
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "detected_outcome=" in result.error
        assert "page_url=" in result.error

    # --- Metadata ---

    @pytest.mark.asyncio
    async def test_apply_url_preserved_in_result(self):
        page = _make_page(textarea_found=True)
        url = "https://hh.ru/vacancy/99999"
        result = await apply_to_vacancy(page, url, "Письмо")
        assert result.apply_url == url

    # --- Cover letter fill verification ---

    @pytest.mark.asyncio
    async def test_cover_letter_fill_called_when_textarea_present(self):
        """textarea.fill() is called when textarea is found and cover_letter provided."""
        page = _make_page(textarea_found=True)

        from connectors.hh_browser import selectors as sel
        captured = []
        original_qs = page.query_selector

        async def capturing_qs(selector):
            el = await original_qs(selector)
            if selector == sel.COVER_LETTER_TEXTAREA and el is not None:
                captured.append(el)
            return el

        page.query_selector = capturing_qs

        await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо 123")

        assert captured, "textarea query_selector should have been called"
        captured[0].fill.assert_called_once_with("Мое письмо 123")

    # --- Cookies ---

    @pytest.mark.asyncio
    async def test_cookies_accepted_on_vacancy_page(self):
        """Cookies banner is dismissed before apply sequence."""
        page = _make_page(cookies_visible=True, textarea_found=True)

        from connectors.hh_browser import selectors as sel
        cookies_clicks = []
        original_qs = page.query_selector

        async def tracking_qs(selector):
            el = await original_qs(selector)
            if selector == sel.COOKIES_ACCEPT and el is not None:
                # Wrap click to track calls
                original_click = el.click
                async def tracked_click():
                    cookies_clicks.append(True)
                    return await original_click()
                el.click = tracked_click
            return el

        page.query_selector = tracking_qs
        await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert cookies_clicks, "cookies accept button should have been clicked"
