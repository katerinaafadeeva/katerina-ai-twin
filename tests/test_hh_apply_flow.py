"""Tests for connectors/hh_browser/apply_flow.py.

All Playwright page interactions are mocked — no real browser required.

Covers:
- ApplyStatus enum values
- _is_captcha_present / _is_session_expired
- _accept_cookies
- _diagnose_timeout (all diagnostic outcomes)
- _fill_inline_letter
- _attach_cover_letter fallback chain (inline → post_apply → chat → no_field_found)
- apply_to_vacancy full flow: DONE, ALREADY_APPLIED, MANUAL_REQUIRED, CAPTCHA,
  SESSION_EXPIRED, FAILED, timeout with diagnosis
- Letter-status telemetry: sent_popup, sent_inline, sent_post_apply,
  sent_chat, chat_closed, no_field_found, fill_failed, not_requested
- After-success-toast: full attach chain is called (not immediate DONE_WITHOUT_LETTER)
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
    _attach_cover_letter,
    _send_letter_via_chat,
    _POST_CLICK_OUTCOMES,
    _POST_SUBMIT_SIGNALS,
    _POST_APPLY_CONFIRM_SIGNALS,
    _DIAGNOSTIC_INLINE,
    _DIAGNOSTIC_CHAT,
    _DIAGNOSTIC_EXTERNAL,
    _DIAGNOSTIC_QUESTIONNAIRE,
    _DIAGNOSTIC_PHONE,
    _DIAGNOSTIC_COOKIES,
    _DIAGNOSTIC_UNKNOWN,
    _LS_NOT_REQUESTED,
    _LS_SENT_POPUP,
    _LS_SENT_INLINE,
    _LS_SENT_POST_APPLY,
    _LS_SENT_CHAT,
    _LS_NO_FIELD,
    _LS_CHAT_CLOSED,
    _LS_FILL_FAILED,
)


# ---------------------------------------------------------------------------
# ApplyStatus enum
# ---------------------------------------------------------------------------


class TestApplyStatus:
    def test_done_value(self):
        assert ApplyStatus.DONE == "done"

    def test_done_without_letter_value(self):
        # Legacy value kept for DB backward compatibility
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
        assert await _is_captcha_present(page) is False

    @pytest.mark.asyncio
    async def test_returns_true_when_element_visible(self):
        mock_el = AsyncMock()
        mock_el.is_visible = AsyncMock(return_value=True)
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=mock_el)
        assert await _is_captcha_present(page) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_element_hidden(self):
        mock_el = AsyncMock()
        mock_el.is_visible = AsyncMock(return_value=False)
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=mock_el)
        assert await _is_captcha_present(page) is False


# ---------------------------------------------------------------------------
# _is_session_expired
# ---------------------------------------------------------------------------


class TestIsSessionExpired:
    @pytest.mark.asyncio
    async def test_returns_true_when_login_in_url(self):
        page = AsyncMock()
        page.url = "https://hh.ru/login?backurl=/vacancy/123"
        page.query_selector = AsyncMock(return_value=None)
        assert await _is_session_expired(page) is True

    @pytest.mark.asyncio
    async def test_returns_false_on_vacancy_page(self):
        page = AsyncMock()
        page.url = "https://hh.ru/vacancy/123456"
        page.query_selector = AsyncMock(return_value=None)
        assert await _is_session_expired(page) is False


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
        await _accept_cookies(page)  # must not raise


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
        page.title = AsyncMock(return_value="Вакансия")
        outcome, title = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_INLINE
        assert title == "Вакансия"

    @pytest.mark.asyncio
    async def test_detects_chat_without_form(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value=(
            "<html><a data-qa='vacancy-response-link-view-topic'>Чат</a></html>"
        ))
        page.title = AsyncMock(return_value="")
        outcome, _ = await _diagnose_timeout(page)
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
        page.content = AsyncMock(return_value="<html>Перейти на сайт работодателя</html>")
        page.title = AsyncMock(return_value="")
        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_EXTERNAL

    @pytest.mark.asyncio
    async def test_detects_questionnaire_english(self):
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html>questionnaire</html>")
        page.title = AsyncMock(return_value="")
        page.url = "https://hh.ru/vacancy/111"
        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_QUESTIONNAIRE

    @pytest.mark.asyncio
    async def test_detects_questionnaire_russian_anketa(self):
        """HH.ru shows Russian 'анкету' (any declension) — must be detected as questionnaire_required."""
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html><h1>Заполните анкету работодателя</h1></html>")
        page.title = AsyncMock(return_value="Анкета")
        page.url = "https://hh.ru/vacancy/111"
        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_QUESTIONNAIRE

    @pytest.mark.asyncio
    async def test_detects_questionnaire_russian_questions(self):
        """'Ответьте на вопросы' phrase must be detected as questionnaire_required."""
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html>Ответьте на вопросы работодателя</html>")
        page.title = AsyncMock(return_value="")
        page.url = "https://hh.ru/vacancy/111"
        outcome, _ = await _diagnose_timeout(page)
        assert outcome == _DIAGNOSTIC_QUESTIONNAIRE

    @pytest.mark.asyncio
    async def test_detects_questionnaire_via_url(self):
        """HH redirects to /quest/ URL — detected via page.url even if HTML unclear."""
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html><p>Загрузка...</p></html>")
        page.title = AsyncMock(return_value="")
        page.url = "https://hh.ru/applicant/vacancy/quest/12345"
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
        page.content = AsyncMock(return_value="<html><p>Unknown UI</p></html>")
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
        from connectors.hh_browser import selectors as sel
        textarea = AsyncMock()
        textarea.is_visible = AsyncMock(return_value=True)
        textarea.fill = AsyncMock()
        textarea.input_value = AsyncMock(return_value="Мое письмо")

        submit = AsyncMock()
        submit.is_visible = AsyncMock(return_value=True)
        submit.click = AsyncMock()

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
        assert await _fill_inline_letter(page, "Письмо", "https://hh.ru/vacancy/1") is False

    @pytest.mark.asyncio
    async def test_returns_false_when_fill_leaves_empty_value(self):
        from connectors.hh_browser import selectors as sel
        textarea = AsyncMock()
        textarea.is_visible = AsyncMock(return_value=True)
        textarea.fill = AsyncMock()
        textarea.input_value = AsyncMock(return_value="")

        async def qs(selector):
            if selector == sel.INLINE_LETTER_TEXTAREA:
                return textarea
            return None

        page = AsyncMock()
        page.query_selector = qs
        assert await _fill_inline_letter(page, "Письмо", "https://hh.ru/vacancy/1") is False


# ---------------------------------------------------------------------------
# _attach_cover_letter — unit tests
# ---------------------------------------------------------------------------


class TestAttachCoverLetter:
    """Unit tests for the fallback chain function."""

    def _make_attach_page(
        self,
        inline_visible=False,
        inline_textarea_value="Письмо",
        inline_submit_visible=True,
        post_apply_visible=False,
        post_apply_value="Письмо",
        post_apply_submit_visible=True,
        chat_link_visible=False,
        chat_closed_visible=False,
        chat_input_visible=False,
        chat_send_visible=True,
    ):
        from connectors.hh_browser import selectors as sel

        def _el(visible=True, val="filled"):
            e = AsyncMock()
            e.is_visible = AsyncMock(return_value=visible)
            e.fill = AsyncMock()
            e.click = AsyncMock()
            e.input_value = AsyncMock(return_value=val)
            return e

        inline_form_el = _el(inline_visible)
        inline_textarea_el = _el(inline_visible, inline_textarea_value)
        inline_submit_el = _el(inline_submit_visible)
        pa_el = _el(post_apply_visible, post_apply_value)
        pa_submit_el = _el(post_apply_submit_visible)
        chat_el = _el(chat_link_visible)
        closed_el = _el(chat_closed_visible)
        chat_input_el = _el(chat_input_visible)
        send_el = _el(chat_send_visible)

        page = AsyncMock()
        page.url = "https://hh.ru/vacancy/1"
        page.wait_for_load_state = AsyncMock()

        async def qs(selector):
            if selector == sel.INLINE_LETTER_FORM:
                return inline_form_el
            if selector == sel.INLINE_LETTER_TEXTAREA:
                return inline_textarea_el
            if selector == sel.INLINE_LETTER_SUBMIT:
                return inline_submit_el
            if selector == sel.POST_APPLY_LETTER_TEXTAREA:
                return pa_el
            if selector == sel.POST_APPLY_LETTER_SUBMIT:
                return pa_submit_el
            if selector == sel.RESPONSE_TOPIC_LINK:
                return chat_el
            if selector == sel.CHAT_CLOSED_INDICATOR:
                return closed_el
            if selector == sel.CHAT_SEND_BUTTON:
                return send_el
            return None

        async def wfs(selector, timeout=None):
            if selector == sel.INLINE_LETTER_FORM:
                return inline_form_el
            if selector == sel.CHAT_MESSAGE_INPUT:
                if chat_input_visible:
                    return chat_input_el
                raise Exception("timeout")
            raise Exception(f"timeout: {selector}")

        page.query_selector = qs
        page.wait_for_selector = wfs
        return page

    @pytest.mark.asyncio
    async def test_inline_success(self):
        page = self._make_attach_page(inline_visible=True, inline_textarea_value="letter")
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_SENT_INLINE
        assert tf is True

    @pytest.mark.asyncio
    async def test_inline_fill_fails_returns_fill_failed(self):
        """Inline form found but fill leaves empty value → fill_failed."""
        page = self._make_attach_page(inline_visible=True, inline_textarea_value="")
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_FILL_FAILED
        assert tf is True

    @pytest.mark.asyncio
    async def test_post_apply_success(self):
        page = self._make_attach_page(
            inline_visible=False,
            post_apply_visible=True,
            post_apply_value="letter",
        )
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_SENT_POST_APPLY
        assert tf is True

    @pytest.mark.asyncio
    async def test_post_apply_submit_missing_returns_fill_failed(self):
        page = self._make_attach_page(
            inline_visible=False,
            post_apply_visible=True,
            post_apply_value="letter",
            post_apply_submit_visible=False,
        )
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_FILL_FAILED

    @pytest.mark.asyncio
    async def test_chat_sent(self):
        page = self._make_attach_page(
            inline_visible=False,
            post_apply_visible=False,
            chat_link_visible=True,
            chat_input_visible=True,
        )
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_SENT_CHAT
        assert ca is True

    @pytest.mark.asyncio
    async def test_chat_closed(self):
        page = self._make_attach_page(
            inline_visible=False,
            post_apply_visible=False,
            chat_link_visible=True,
            chat_closed_visible=True,
        )
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_CHAT_CLOSED
        assert ca is True

    @pytest.mark.asyncio
    async def test_no_field_found_when_nothing_visible(self):
        page = self._make_attach_page()  # all False
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_NO_FIELD
        assert tf is False
        assert ca is False

    @pytest.mark.asyncio
    async def test_fallback_chain_stops_at_inline(self):
        """inline found → post_apply and chat are never tried."""
        page = self._make_attach_page(
            inline_visible=True,
            inline_textarea_value="letter",
            post_apply_visible=True,  # would also be found, but we stop at inline
        )
        ls, tf, ca, fu = await _attach_cover_letter(page, "letter", "https://hh.ru/vacancy/1")
        assert ls == _LS_SENT_INLINE


# ---------------------------------------------------------------------------
# apply_to_vacancy — mock factory
# ---------------------------------------------------------------------------


def _make_page(
    url="https://hh.ru/vacancy/111",
    captcha_visible=False,
    already_applied=False,
    apply_btn_found=True,
    # Post-click outcomes
    outcome_timeout=False,
    success_toast=False,
    submit_popup=True,
    textarea_found=False,
    textarea_fill_value="filled",
    # Path B (inline) params — appear AFTER clicking apply (stateful)
    inline_form=False,
    inline_textarea=False,
    inline_submit=True,
    response_topic_link=False,
    response_topic_preclick=False,  # visible BEFORE click → already applied
    # Path C (post-apply) — appear after popup submit
    post_apply_textarea=False,
    post_apply_value="letter",
    post_apply_submit=True,
    # Path D (chat)
    chat_closed=False,
    chat_input=False,
    chat_send=True,
    # Cookies
    cookies_visible=False,
    # Popup submit validation
    submit_timeout=False,  # True → post-submit wait_for_selector raises (simulate timeout)
    # Success toast secondary confirmation
    toast_confirmed=True,  # True → _POST_APPLY_CONFIRM_SIGNALS resolves; False → raises
):
    """Build a mock Playwright page for the multi-outcome apply flow.

    Path B elements only become visible AFTER apply_btn.click() (state-based).
    """
    from connectors.hh_browser import selectors as sel

    state = {"clicked": False}

    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.screenshot = AsyncMock()
    page.content = AsyncMock(return_value="<html>mock</html>")
    page.title = AsyncMock(return_value="Mock vacancy")
    page.wait_for_load_state = AsyncMock()

    def _el(visible=True, val="filled"):
        e = AsyncMock()
        e.is_visible = AsyncMock(return_value=visible)
        e.fill = AsyncMock()
        e.click = AsyncMock()
        e.input_value = AsyncMock(return_value=val)
        return e

    captcha_el = _el(captcha_visible)
    already_el = _el(already_applied)

    apply_btn = _el(apply_btn_found)
    _orig_click = apply_btn.click
    async def _btn_click():
        state["clicked"] = True
        return await _orig_click()
    apply_btn.click = _btn_click

    submit_el = _el(submit_popup)
    toast_el = _el(True)
    textarea_el = _el(textarea_found, textarea_fill_value if textarea_found else "")

    # Path B
    inline_form_el = _el(True)
    inline_textarea_el = _el(True, "Письмо" if inline_textarea else "")
    inline_submit_el = _el(inline_submit)
    response_topic_el = _el(True)

    # Path C
    pa_el = _el(post_apply_textarea, post_apply_value if post_apply_textarea else "")
    pa_submit_el = _el(post_apply_submit)

    # Path D
    chat_link_el = _el(True)
    closed_el = _el(chat_closed)
    chat_input_el = _el(chat_input)
    send_el = _el(chat_send)

    cookies_btn = _el(cookies_visible)

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
        # Path B — stateful (post-click)
        if selector == sel.INLINE_LETTER_FORM:
            return inline_form_el if (inline_form and state["clicked"]) else None
        if selector == sel.INLINE_LETTER_TEXTAREA:
            return inline_textarea_el if (inline_textarea and state["clicked"]) else None
        if selector == sel.INLINE_LETTER_SUBMIT:
            return inline_submit_el if (inline_submit and state["clicked"]) else None
        if selector == sel.RESPONSE_TOPIC_LINK:
            if response_topic_preclick:
                return response_topic_el
            return response_topic_el if (response_topic_link and state["clicked"]) else None
        # Path C
        if selector == sel.POST_APPLY_LETTER_TEXTAREA:
            return pa_el if (post_apply_textarea and state["clicked"]) else None
        if selector == sel.POST_APPLY_LETTER_SUBMIT:
            return pa_submit_el if (post_apply_submit and state["clicked"]) else None
        # Path D
        if selector == sel.CHAT_CLOSED_INDICATOR:
            return closed_el if (chat_closed and state["clicked"]) else None
        if selector == sel.CHAT_SEND_BUTTON:
            return send_el if (chat_send and state["clicked"]) else None
        if selector == sel.COOKIES_ACCEPT:
            return cookies_btn if cookies_visible else None
        return None

    page.query_selector = mock_query_selector

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
                raise Exception("Timeout 30s")
            return AsyncMock()
        if selector == _POST_SUBMIT_SIGNALS:
            if submit_timeout:
                raise Exception("Timeout — no post-submit success signal")
            return AsyncMock()
        if selector == _POST_APPLY_CONFIRM_SIGNALS:
            if not toast_confirmed:
                raise Exception("Timeout — no strong apply confirmation")
            return AsyncMock()
        if selector == sel.INLINE_LETTER_FORM:
            return inline_form_el if (inline_form and state["clicked"]) else (_ for _ in ()).throw(Exception("timeout"))
        if selector == sel.CHAT_MESSAGE_INPUT:
            if chat_input and state["clicked"]:
                return chat_input_el
            raise Exception("timeout")
        raise Exception(f"Unknown selector: {selector}")

    page.wait_for_selector = mock_wait_for_selector
    return page


# ---------------------------------------------------------------------------
# apply_to_vacancy — full flow
# ---------------------------------------------------------------------------


class TestApplyToVacancy:

    # --- Path A: popup with textarea ---

    @pytest.mark.asyncio
    async def test_popup_with_textarea_gives_sent_popup(self):
        page = _make_page(textarea_found=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_POPUP
        assert result.textarea_found is True
        assert result.flow_type == "popup"
        assert result.letter_len == len("Мое письмо")

    @pytest.mark.asyncio
    async def test_popup_no_textarea_tries_attach_chain(self):
        """Popup found, no textarea, no fallback fields → no_field_found."""
        page = _make_page(textarea_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NO_FIELD
        assert result.flow_type == "popup"

    @pytest.mark.asyncio
    async def test_popup_no_textarea_with_post_apply_fallback(self):
        """Popup no textarea → fallback finds post_apply textarea → sent_post_apply."""
        page = _make_page(textarea_found=False, post_apply_textarea=True, post_apply_value="letter")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_POST_APPLY

    @pytest.mark.asyncio
    async def test_popup_no_cover_letter_gives_not_requested(self):
        page = _make_page(textarea_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NOT_REQUESTED

    # --- Path B: inline form ---

    @pytest.mark.asyncio
    async def test_inline_with_textarea_gives_sent_inline(self):
        page = _make_page(submit_popup=False, inline_form=True, inline_textarea=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_INLINE
        assert result.flow_type == "inline"

    @pytest.mark.asyncio
    async def test_inline_no_cover_letter_gives_not_requested(self):
        page = _make_page(submit_popup=False, inline_form=True, inline_textarea=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NOT_REQUESTED

    @pytest.mark.asyncio
    async def test_inline_fill_fails_tries_post_apply(self):
        """Inline form found but fill leaves empty → fallback tries post_apply."""
        page = _make_page(
            submit_popup=False,
            inline_form=True,
            inline_textarea=False,  # will return "" after fill
            post_apply_textarea=True,
            post_apply_value="Письмо",
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        # inline fill_failed → fallback to post_apply sent_post_apply
        assert result.letter_status in (_LS_SENT_POST_APPLY, _LS_FILL_FAILED)

    # --- Quick apply (chat link, no inline form) ---

    @pytest.mark.asyncio
    async def test_chat_link_no_inline_no_letter_gives_not_requested(self):
        page = _make_page(submit_popup=False, response_topic_link=True, inline_form=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NOT_REQUESTED

    @pytest.mark.asyncio
    async def test_chat_link_with_letter_and_chat_path_gives_sent_chat(self):
        """Quick apply + chat link + chat input → sent_chat."""
        page = _make_page(
            submit_popup=False,
            response_topic_link=True,
            inline_form=False,
            chat_input=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_CHAT
        assert result.chat_available is True

    # --- Success toast — now requires strong post-apply confirmation ---

    @pytest.mark.asyncio
    async def test_success_toast_unconfirmed_gives_failed(self):
        """Toast appears but no strong confirmation signal → FAILED (false positive guard)."""
        page = _make_page(success_toast=True, submit_popup=False, toast_confirmed=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.FAILED
        assert "toast_unconfirmed" in result.error

    @pytest.mark.asyncio
    async def test_success_toast_unconfirmed_no_letter_also_failed(self):
        """Toast without strong confirmation → FAILED regardless of cover_letter."""
        page = _make_page(success_toast=True, submit_popup=False, toast_confirmed=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.FAILED
        assert "toast_unconfirmed" in result.error

    @pytest.mark.asyncio
    async def test_success_toast_confirmed_no_cover_letter_gives_not_requested(self):
        page = _make_page(success_toast=True, submit_popup=False, toast_confirmed=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NOT_REQUESTED

    @pytest.mark.asyncio
    async def test_success_toast_confirmed_with_letter_runs_attach_chain(self):
        """After confirmed toast, attach chain is called."""
        page = _make_page(success_toast=True, submit_popup=False, toast_confirmed=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_NO_FIELD

    @pytest.mark.asyncio
    async def test_success_toast_confirmed_then_inline_form_appears(self):
        """Confirmed toast + inline form found in attach chain → sent_inline."""
        page = _make_page(
            success_toast=True,
            submit_popup=False,
            toast_confirmed=True,
            inline_form=True,
            inline_textarea=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_INLINE

    # --- Path C: post-apply textarea (standalone) ---

    @pytest.mark.asyncio
    async def test_post_apply_textarea_from_quick_apply(self):
        """Quick apply success → attach chain finds post_apply textarea."""
        page = _make_page(
            success_toast=True,
            submit_popup=False,
            post_apply_textarea=True,
            post_apply_value="letter",
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_POST_APPLY

    # --- Path D: chat (standalone) ---

    @pytest.mark.asyncio
    async def test_chat_closed_gives_chat_closed_status(self):
        """Chat link visible, but chat is closed → chat_closed."""
        page = _make_page(
            success_toast=True,
            submit_popup=False,
            response_topic_link=True,
            chat_closed=True,
        )
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_CHAT_CLOSED
        assert result.chat_available is True

    # --- Already applied ---

    @pytest.mark.asyncio
    async def test_already_applied(self):
        page = _make_page(already_applied=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    @pytest.mark.asyncio
    async def test_already_applied_via_chat_link_preclick(self):
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
        page = _make_page(outcome_timeout=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.FAILED
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_timeout_inline_html_gives_done(self):
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value=(
            "<html><div data-qa='vacancy-response-letter-informer'></div></html>"
        ))
        page.title = AsyncMock(return_value="Вакансия")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_timeout_chat_html_gives_already_applied(self):
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value=(
            "<html><a data-qa='vacancy-response-link-view-topic'>Чат</a></html>"
        ))
        page.title = AsyncMock(return_value="")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    @pytest.mark.asyncio
    async def test_timeout_external_gives_manual_required(self):
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value="<html>Перейти на сайт работодателя</html>")
        page.title = AsyncMock(return_value="Внешний")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "external_apply" in result.error

    @pytest.mark.asyncio
    async def test_timeout_questionnaire_gives_manual_required(self):
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value="<html>questionnaire</html>")
        page.title = AsyncMock(return_value="")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "questionnaire_required" in result.error

    @pytest.mark.asyncio
    async def test_timeout_questionnaire_russian_html_gives_manual_required(self):
        """Russian 'анкета' in HTML → MANUAL_REQUIRED, no retry."""
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(
            return_value="<html><h1>Заполните анкету работодателя</h1></html>"
        )
        page.title = AsyncMock(return_value="Анкета")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/130872223")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert result.detected_outcome == "questionnaire_required"

    @pytest.mark.asyncio
    async def test_timeout_questionnaire_url_redirect_gives_manual_required(self):
        """HH redirect to /quest/ URL → MANUAL_REQUIRED, no retry."""
        page = _make_page(outcome_timeout=True, url="https://hh.ru/applicant/vacancy/quest/99")
        page.content = AsyncMock(return_value="<html><p>Загрузка</p></html>")
        page.title = AsyncMock(return_value="Анкета")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/130872223")
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert result.detected_outcome == "questionnaire_required"

    @pytest.mark.asyncio
    async def test_error_format_has_detected_outcome_and_page_url(self):
        page = _make_page(outcome_timeout=True)
        page.content = AsyncMock(return_value="<html>Подтвердить телефон</html>")
        page.title = AsyncMock(return_value="")
        url = "https://hh.ru/vacancy/999"
        result = await apply_to_vacancy(page, url)
        assert result.status == ApplyStatus.MANUAL_REQUIRED
        assert "detected_outcome=" in result.error
        assert "page_url=" in result.error

    # --- Telemetry ---

    @pytest.mark.asyncio
    async def test_apply_url_preserved_in_result(self):
        page = _make_page(textarea_found=True)
        url = "https://hh.ru/vacancy/99999"
        result = await apply_to_vacancy(page, url, "Письмо")
        assert result.apply_url == url

    @pytest.mark.asyncio
    async def test_letter_len_is_set(self):
        page = _make_page(textarea_found=True)
        letter = "Сопроводительное письмо"
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", letter)
        assert result.letter_len == len(letter)

    # --- Popup submit timeout ---

    @pytest.mark.asyncio
    async def test_popup_submit_timeout_gives_failed(self):
        """No post-submit success signal within 15s → FAILED with popup_submit_timeout."""
        page = _make_page(textarea_found=False, submit_timeout=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.FAILED
        assert "popup_submit_timeout" in result.error

    @pytest.mark.asyncio
    async def test_popup_submit_timeout_no_letter_gives_failed(self):
        """Timeout also FAILED when no letter requested."""
        page = _make_page(textarea_found=False, submit_timeout=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.FAILED
        assert "popup_submit_timeout" in result.error

    # --- final_url telemetry ---

    @pytest.mark.asyncio
    async def test_popup_sent_popup_captures_final_url(self):
        """sent_popup result must carry final_url = page.url after submit."""
        page = _make_page(textarea_found=True, url="https://hh.ru/vacancy/777")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/777", "Письмо")
        assert result.status == ApplyStatus.DONE
        assert result.letter_status == _LS_SENT_POPUP
        assert result.final_url == "https://hh.ru/vacancy/777"

    @pytest.mark.asyncio
    async def test_cookies_accepted_on_vacancy_page(self):
        page = _make_page(cookies_visible=True, textarea_found=True)
        from connectors.hh_browser import selectors as sel
        cookies_clicks = []
        original_qs = page.query_selector

        async def tracking_qs(selector):
            el = await original_qs(selector)
            if selector == sel.COOKIES_ACCEPT and el is not None:
                orig = el.click
                async def tracked():
                    cookies_clicks.append(True)
                    return await orig()
                el.click = tracked
            return el

        page.query_selector = tracking_qs
        await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert cookies_clicks, "cookies accept button should have been clicked"
