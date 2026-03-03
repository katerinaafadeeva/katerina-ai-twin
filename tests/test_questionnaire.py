"""Tests for HH.ru employer questionnaire auto-fill.

Covers:
- Salary question detection and filling with profile salary range
- Location / experience / start-date question detection
- Unknown questions skipped and reported
- Dropdown (select) skipped
- All-filled vs partial-filled return values
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(blocks: list):
    """Return a mock Playwright page with given question blocks."""
    page = MagicMock()
    page.query_selector_all = AsyncMock(return_value=blocks)
    return page


def _make_block(label_text: str, input_type: str = "text", visible: bool = True):
    """Return a mock question block with given label and input type."""
    block = MagicMock()
    block.is_visible = AsyncMock(return_value=visible)
    block.inner_text = AsyncMock(return_value=label_text)

    # Label element
    label_el = MagicMock()
    label_el.is_visible = AsyncMock(return_value=True)
    label_el.inner_text = AsyncMock(return_value=label_text)
    block.query_selector = AsyncMock(return_value=label_el)

    # Input element
    input_el = MagicMock()
    input_el.is_visible = AsyncMock(return_value=True)
    _filled = []
    async def _fill(v):
        _filled.append(v)
    input_el.fill = _fill
    input_el.input_value = AsyncMock(return_value="filled_value")
    input_el._filled = _filled

    if input_type == "text":
        block.query_selector_side_effects = {
            "input[type='text'], input[type='number'], input:not([type='checkbox']):not([type='radio'])": input_el,
            "textarea": None,
            "select": None,
        }
    elif input_type == "textarea":
        block.query_selector_side_effects = {
            "input[type='text'], input[type='number'], input:not([type='checkbox']):not([type='radio'])": None,
            "textarea": input_el,
            "select": None,
        }
    elif input_type == "select":
        block.query_selector_side_effects = {
            "input[type='text'], input[type='number'], input:not([type='checkbox']):not([type='radio'])": None,
            "textarea": None,
            "select": input_el,
        }
    elif input_type == "none":
        block.query_selector_side_effects = {
            "input[type='text'], input[type='number'], input:not([type='checkbox']):not([type='radio'])": None,
            "textarea": None,
            "select": None,
        }

    async def _query_selector(sel):
        if sel == "label":
            return label_el
        return block.query_selector_side_effects.get(sel)

    block.query_selector = AsyncMock(side_effect=_query_selector)
    block._input_el = input_el
    return block


def _make_profile(salary_min: int = 150_000):
    """Return a mock profile with salary floor."""
    profile = MagicMock()
    profile.must_have = {"salary_min_rub": salary_min}
    profile.location_base = "Москва"
    return profile


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSalaryQuestion:
    @pytest.mark.asyncio
    async def test_salary_question_filled(self):
        """Salary question → fills with derived salary range."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Укажите желаемый уровень дохода", input_type="text")
        page = _make_page([block])
        profile = _make_profile(salary_min=150_000)

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, profile, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert len(filled) == 1
        assert len(skipped) == 0
        # The input should have been filled with salary answer
        assert len(block._input_el._filled) == 1
        answer = block._input_el._filled[0]
        assert "000" in answer  # contains salary numbers

    @pytest.mark.asyncio
    async def test_salary_keyword_variants(self):
        """Various salary-related question labels should be detected."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        for label in (
            "Укажите зарплатные ожидания",
            "Желаемый доход",
            "Ожидаемое вознаграждение",
            "Expected salary",
        ):
            block = _make_block(label, input_type="text")
            page = _make_page([block])
            profile = _make_profile()

            all_filled, filled, skipped = await fill_popup_questionnaire(
                page, profile, "https://hh.ru/vacancy/1"
            )
            assert all_filled is True, f"Salary label {label!r} not detected"
            assert len(block._input_el._filled) == 1

    @pytest.mark.asyncio
    async def test_salary_range_derived_from_profile(self):
        """Salary answer derives range from profile.must_have.salary_min_rub."""
        from connectors.hh_browser.questionnaire import _build_salary_answer

        profile = _make_profile(salary_min=200_000)
        answer = _build_salary_answer(profile)
        assert "000" in answer
        # Floor 200k → low ~240 (200*1.2), high ~340 (200*1.7)
        assert "240" in answer or "200" in answer  # approximate check


class TestLocationAndOtherQuestions:
    @pytest.mark.asyncio
    async def test_location_question_filled(self):
        """Location question → fills with profile.location_base."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Укажите ваш город", input_type="text")
        page = _make_page([block])
        profile = _make_profile()

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, profile, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert len(filled) == 1
        assert block._input_el._filled[0] == "Москва"

    @pytest.mark.asyncio
    async def test_experience_question_filled(self):
        """Experience question → fills with '5+ лет'."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Ваш опыт работы в годах", input_type="text")
        page = _make_page([block])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert "5+" in block._input_el._filled[0]

    @pytest.mark.asyncio
    async def test_start_date_question_filled(self):
        """Start date question → fills with availability answer."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Когда готовы приступить к работе?", input_type="text")
        page = _make_page([block])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert "недел" in block._input_el._filled[0].lower()


class TestUnanswerableQuestions:
    @pytest.mark.asyncio
    async def test_unknown_question_skipped(self):
        """Unknown question type → skipped, returned in skipped_labels."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Почему вы хотите работать в нашей компании?", input_type="text")
        page = _make_page([block])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        assert all_filled is False
        assert len(skipped) == 1
        assert len(filled) == 0

    @pytest.mark.asyncio
    async def test_select_dropdown_skipped(self):
        """Select (dropdown) input → skipped regardless of question type."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Желаемый уровень дохода", input_type="select")
        page = _make_page([block])
        profile = _make_profile()

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, profile, "https://hh.ru/vacancy/1"
        )

        assert all_filled is False
        assert len(skipped) == 1

    @pytest.mark.asyncio
    async def test_no_input_element_silently_skipped(self):
        """Question block with no fillable input → silently skipped (not counted as unanswered)."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Some label", input_type="none")
        page = _make_page([block])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        # No fillable input → not counted as a failure
        assert all_filled is True
        assert len(filled) == 0
        assert len(skipped) == 0

    @pytest.mark.asyncio
    async def test_mixed_questions_partial_fill(self):
        """Salary (filled) + unknown (skipped) → not all_filled."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        salary_block = _make_block("Укажите ожидаемую зарплату", input_type="text")
        unknown_block = _make_block("Расскажите о себе", input_type="text")
        page = _make_page([salary_block, unknown_block])
        profile = _make_profile()

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, profile, "https://hh.ru/vacancy/1"
        )

        assert all_filled is False
        assert len(filled) == 1
        assert len(skipped) == 1

    @pytest.mark.asyncio
    async def test_no_questions_returns_true(self):
        """Empty question list → all_filled=True, nothing skipped."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        page = _make_page([])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert filled == []
        assert skipped == []

    @pytest.mark.asyncio
    async def test_invisible_block_ignored(self):
        """Invisible question block → ignored, not counted."""
        from connectors.hh_browser.questionnaire import fill_popup_questionnaire

        block = _make_block("Hidden question", input_type="text", visible=False)
        page = _make_page([block])

        all_filled, filled, skipped = await fill_popup_questionnaire(
            page, None, "https://hh.ru/vacancy/1"
        )

        assert all_filled is True
        assert len(filled) == 0
        assert len(skipped) == 0
