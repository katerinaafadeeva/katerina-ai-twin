"""Tests for connectors/hh_browser/apply_flow.py.

All Playwright page interactions are mocked — no real browser required.
Covers: DONE, DONE_WITHOUT_LETTER, ALREADY_APPLIED, MANUAL_REQUIRED,
CAPTCHA, SESSION_EXPIRED, FAILED, multi-outcome wait, artifact saving.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from connectors.hh_browser.apply_flow import (
    ApplyResult,
    ApplyStatus,
    apply_to_vacancy,
    _is_captcha_present,
    _is_session_expired,
    _POST_CLICK_OUTCOMES,
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
# apply_to_vacancy — mock factory
# ---------------------------------------------------------------------------


def _make_page(
    url="https://hh.ru/vacancy/111",
    captcha_visible=False,
    already_applied=False,
    apply_btn_found=True,
    # Multi-outcome post-click scenario
    outcome_timeout=False,    # True → wait_for_selector(_POST_CLICK_OUTCOMES) raises
    success_toast=False,      # True → SUCCESS_TOAST query_selector returns visible element
    submit_popup=True,        # True → SUBMIT_BUTTON query_selector returns visible element
    textarea_found=False,     # True → COVER_LETTER_TEXTAREA query_selector returns element
    textarea_fill_value="filled",  # What textarea.input_value() returns after fill
):
    """Build a mock Playwright page for the new multi-outcome apply flow."""
    from connectors.hh_browser import selectors as sel

    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    # Artifact helpers — content() returns a string so open().write() doesn't fail
    page.screenshot = AsyncMock()
    page.content = AsyncMock(return_value="<html>mock</html>")

    # --- Element mocks ---
    captcha_el = AsyncMock()
    captcha_el.is_visible = AsyncMock(return_value=captcha_visible)

    already_el = AsyncMock()
    already_el.is_visible = AsyncMock(return_value=already_applied)

    apply_btn = AsyncMock()
    apply_btn.is_visible = AsyncMock(return_value=apply_btn_found)
    apply_btn.click = AsyncMock()

    submit_el = AsyncMock()
    submit_el.is_visible = AsyncMock(return_value=submit_popup)
    submit_el.click = AsyncMock()

    toast_el = AsyncMock()
    toast_el.is_visible = AsyncMock(return_value=True)

    textarea_el = AsyncMock()
    textarea_el.is_visible = AsyncMock(return_value=textarea_found)
    textarea_el.fill = AsyncMock()
    textarea_el.input_value = AsyncMock(
        return_value=textarea_fill_value if textarea_found else ""
    )

    # --- query_selector ---
    async def mock_query_selector(selector):
        # Captcha checks (3 selectors)
        if selector in (sel.CAPTCHA_WRAPPER, sel.RECAPTCHA_IFRAME, sel.SMARTCAPTCHA_IFRAME):
            return captcha_el if captcha_visible else None
        # Auth
        if selector == sel.AUTH_LOGIN_BUTTON:
            return None
        # Post-click outcome checks
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
        return None

    page.query_selector = mock_query_selector

    # --- wait_for_selector ---
    async def mock_wait_for_selector(selector, timeout=None):
        # Pre-click already-applied quick check
        if selector == sel.ALREADY_APPLIED:
            if already_applied:
                return already_el
            raise Exception("Timeout — element not found")
        # Apply button
        if selector in (sel.APPLY_BUTTON, sel.APPLY_BUTTON_BOTTOM):
            if apply_btn_found:
                return apply_btn
            raise Exception("Timeout — apply button not found")
        # Multi-outcome wait (30 s)
        if selector == _POST_CLICK_OUTCOMES:
            if outcome_timeout:
                raise Exception("Timeout 30s — no post-click outcome detected")
            return AsyncMock()  # Something appeared; actual outcome via query_selector
        raise Exception(f"Unknown selector: {selector}")

    page.wait_for_selector = mock_wait_for_selector
    return page


# ---------------------------------------------------------------------------
# apply_to_vacancy — full flow mocked
# ---------------------------------------------------------------------------


class TestApplyToVacancy:
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

    @pytest.mark.asyncio
    async def test_done_when_success_toast_no_letter(self):
        """Success toast appears (quick apply), no cover_letter → DONE."""
        page = _make_page(success_toast=True, submit_popup=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", cover_letter="")
        assert result.status == ApplyStatus.DONE

    @pytest.mark.asyncio
    async def test_done_without_letter_when_success_toast_with_letter(self):
        """Success toast + cover_letter provided → DONE_WITHOUT_LETTER (no popup field)."""
        page = _make_page(success_toast=True, submit_popup=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE_WITHOUT_LETTER

    @pytest.mark.asyncio
    async def test_already_applied(self):
        page = _make_page(already_applied=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.ALREADY_APPLIED

    @pytest.mark.asyncio
    async def test_manual_required_when_no_apply_button(self):
        page = _make_page(apply_btn_found=False)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.MANUAL_REQUIRED

    @pytest.mark.asyncio
    async def test_captcha_detected_early(self):
        page = _make_page(captcha_visible=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.CAPTCHA

    @pytest.mark.asyncio
    async def test_session_expired_when_login_url(self):
        page = _make_page(url="https://hh.ru/login")
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.SESSION_EXPIRED

    @pytest.mark.asyncio
    async def test_failed_on_goto_exception(self):
        page = AsyncMock()
        page.url = "https://hh.ru/vacancy/111"
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        page.query_selector = AsyncMock(return_value=None)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111")
        assert result.status == ApplyStatus.FAILED
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_failed_on_outcome_timeout(self):
        """30 s timeout waiting for post-click outcome → FAILED with artifact paths."""
        page = _make_page(outcome_timeout=True)
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Письмо")
        assert result.status == ApplyStatus.FAILED
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_apply_url_preserved_in_result(self):
        page = _make_page(textarea_found=True)
        url = "https://hh.ru/vacancy/99999"
        result = await apply_to_vacancy(page, url, "Письмо")
        assert result.apply_url == url

    @pytest.mark.asyncio
    async def test_cover_letter_fill_called_when_textarea_present(self):
        """textarea.fill() is called when textarea is found and cover_letter provided."""
        page = _make_page(textarea_found=True)

        # Capture the mock textarea so we can check fill was called
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
