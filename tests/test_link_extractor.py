"""Tests for link_extractor module."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from capabilities.career_os.skills.link_extractor.extractor import (
    extract_links_and_content,
    _fetch_hh_vacancy,
)


@pytest.mark.asyncio
async def test_no_urls_returns_original_text():
    text = "Вакансия без ссылок — Product Manager, 5 лет опыта"
    result = await extract_links_and_content(text)
    assert result["hh_vacancy_id"] is None
    assert result["extracted_text"] is None
    assert result["original_text"] == text


@pytest.mark.asyncio
async def test_extract_hh_vacancy_url():
    text = "Отличная вакансия https://hh.ru/vacancy/12345678 — откликнись!"

    async def mock_fetch(vacancy_id):
        return f"Позиция: PM\nКомпания: ACME"

    with patch(
        "capabilities.career_os.skills.link_extractor.extractor._fetch_hh_vacancy",
        side_effect=mock_fetch,
    ):
        result = await extract_links_and_content(text)

    assert result["hh_vacancy_id"] == "12345678"
    assert result["extracted_url"] == "https://hh.ru/vacancy/12345678"


@pytest.mark.asyncio
async def test_extract_non_hh_url_with_keyword():
    text = "Подробнее о вакансии: https://example.com/jobs/pm описание должности"

    async def mock_page(url):
        return "Полный текст вакансии Product Manager с детальными требованиями, обязанностями и условиями работы в компании"

    with patch(
        "capabilities.career_os.skills.link_extractor.extractor._fetch_page_text",
        side_effect=mock_page,
    ):
        result = await extract_links_and_content(text)

    assert result["extracted_url"] == "https://example.com/jobs/pm"
    assert result["extracted_text"] is not None


@pytest.mark.asyncio
async def test_hh_fetch_failure_returns_none_text():
    text = "Вакансия https://hh.ru/vacancy/99999"

    with patch(
        "capabilities.career_os.skills.link_extractor.extractor._fetch_hh_vacancy",
        side_effect=Exception("network error"),
    ):
        result = await extract_links_and_content(text)

    assert result["hh_vacancy_id"] == "99999"
    assert result["extracted_text"] is None
