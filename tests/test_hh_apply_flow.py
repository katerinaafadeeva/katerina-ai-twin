"""Tests for connectors/hh_browser/apply_flow.py.

All Playwright page interactions are mocked — no real browser required.
Covers: DONE, ALREADY_APPLIED, MANUAL_REQUIRED, CAPTCHA, SESSION_EXPIRED, FAILED,
and individual helper functions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from connectors.hh_browser.apply_flow import (
    ApplyResult,
    ApplyStatus,
    apply_to_vacancy,
    _is_captcha_present,
    _is_session_expired,
)


# ---------------------------------------------------------------------------
# ApplyStatus enum
# ---------------------------------------------------------------------------


class TestApplyStatus:
    def test_done_value(self):
        assert ApplyStatus.DONE == "done"

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
# apply_to_vacancy — full flow mocked
# ---------------------------------------------------------------------------


def _make_page(
    url="https://hh.ru/vacancy/111",
    captcha_visible=False,
    already_applied=False,
    apply_btn_found=True,
    submit_btn_found=True,
    textarea_found=False,
):
    """Build a mock Playwright page for the apply flow."""
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()

    # query_selector: captcha selectors return visible element when captcha_visible=True;
    # auth selectors always return None (not on login page) so session check passes.
    captcha_el = AsyncMock()
    captcha_el.is_visible = AsyncMock(return_value=captcha_visible)

    from connectors.hh_browser import selectors as sel

    async def mock_query_selector(selector):
        if selector in (sel.CAPTCHA_WRAPPER, sel.RECAPTCHA_IFRAME, sel.SMARTCAPTCHA_IFRAME):
            return captcha_el if captcha_visible else None
        # AUTH selectors — return None (not on login page)
        return None

    page.query_selector = mock_query_selector

    # wait_for_selector — returns different elements based on selector name
    already_el = AsyncMock()
    already_el.is_visible = AsyncMock(return_value=already_applied)

    apply_btn = AsyncMock()
    apply_btn.is_visible = AsyncMock(return_value=apply_btn_found)
    apply_btn.click = AsyncMock()

    submit_btn = AsyncMock()
    submit_btn.click = AsyncMock()

    textarea = AsyncMock()
    textarea.is_visible = AsyncMock(return_value=textarea_found)
    textarea.fill = AsyncMock()

    async def mock_wait_for_selector(selector, timeout=None):
        from connectors.hh_browser import selectors as sel
        if selector == sel.ALREADY_APPLIED:
            if already_applied:
                return already_el
            raise Exception("Timeout — element not found")
        if selector in (sel.APPLY_BUTTON, sel.APPLY_BUTTON_BOTTOM):
            if apply_btn_found:
                return apply_btn
            raise Exception("Timeout — apply button not found")
        if selector == sel.COVER_LETTER_TEXTAREA:
            if textarea_found:
                return textarea
            raise Exception("Timeout — textarea not found")
        if selector == sel.SUBMIT_BUTTON:
            if submit_btn_found:
                return submit_btn
            raise Exception("Timeout — submit not found")
        raise Exception(f"Unknown selector: {selector}")

    page.wait_for_selector = mock_wait_for_selector
    return page


class TestApplyToVacancy:
    @pytest.mark.asyncio
    async def test_done_on_success(self):
        page = _make_page()
        result = await apply_to_vacancy(page, "https://hh.ru/vacancy/111", "Мое письмо")
        assert result.status == ApplyStatus.DONE

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
    async def test_apply_url_preserved_in_result(self):
        page = _make_page()
        url = "https://hh.ru/vacancy/99999"
        result = await apply_to_vacancy(page, url)
        assert result.apply_url == url
