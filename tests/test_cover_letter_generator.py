"""Tests for capabilities/career_os/skills/cover_letter/generator.py.

Covers:
- get_fallback_letter: loads from example file, uses hardcoded default when absent
- fallback cache invalidation between tests
- generate_cover_letter: success path (mocked Anthropic), fallback on LLM error,
  fallback on too-short response, emits llm.call event
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from capabilities.career_os.models import Profile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile() -> Profile:
    return Profile(
        target_roles=("Product Manager",),
        target_seniority=("senior",),
        work_format=("remote",),
        geo_cities=("Москва",),
        relocation=False,
        salary_min=200_000,
        salary_currency="RUB",
        required_skills=("product management",),
        bonus_skills=(),
        negative_signals=(),
        industries_preferred=(),
        industries_excluded=(),
        languages=("Russian",),
    )


def _mock_anthropic_response(text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = text
    usage = MagicMock()
    usage.input_tokens = 200
    usage.output_tokens = 150
    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


# ---------------------------------------------------------------------------
# get_fallback_letter
# ---------------------------------------------------------------------------


class TestGetFallbackLetter:
    def setup_method(self):
        """Reset module-level cache before each test."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

    def test_loads_from_example_file_when_real_absent(self, tmp_path, monkeypatch):
        """When real file absent but .example.txt exists, use example."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

        example_path = tmp_path / "cover_letter_fallback.example.txt"
        example_path.write_text("Пример сопроводительного письма из файла.", encoding="utf-8")

        # Point module-level config to nonexistent real file in the same dir
        real_path = tmp_path / "cover_letter_fallback.txt"
        mock_cfg = MagicMock()
        mock_cfg.cover_letter_fallback_path = str(real_path)
        monkeypatch.setattr(gen, "config", mock_cfg)

        result = gen.get_fallback_letter()
        assert "Пример сопроводительного" in result

    def test_uses_hardcoded_default_when_no_files(self, tmp_path, monkeypatch):
        """When neither real nor example file exists, return hardcoded default."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

        nonexistent = tmp_path / "missing.txt"
        mock_cfg = MagicMock()
        mock_cfg.cover_letter_fallback_path = str(nonexistent)
        monkeypatch.setattr(gen, "config", mock_cfg)

        result = gen.get_fallback_letter()
        assert len(result) > 20
        assert isinstance(result, str)

    def test_cached_after_first_load(self, tmp_path, monkeypatch):
        """Second call returns same object (cached)."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

        example_path = tmp_path / "cover_letter_fallback.example.txt"
        example_path.write_text("Кешированное письмо.", encoding="utf-8")
        real_path = tmp_path / "cover_letter_fallback.txt"
        mock_cfg = MagicMock()
        mock_cfg.cover_letter_fallback_path = str(real_path)
        monkeypatch.setattr(gen, "config", mock_cfg)

        first = gen.get_fallback_letter()
        # Remove the file — second call should still return cached value
        example_path.unlink()
        second = gen.get_fallback_letter()
        assert first == second


# ---------------------------------------------------------------------------
# generate_cover_letter
# ---------------------------------------------------------------------------


class TestGenerateCoverLetter:
    def setup_method(self):
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

    @pytest.mark.asyncio
    async def test_success_returns_letter_text(self, monkeypatch):
        """On successful LLM call, returns letter_text with is_fallback=False."""
        letter = "Добрый день!\n\nЯ заинтересована в вашей вакансии Product Manager. " \
                 "Мой опыт в управлении продуктом и работе с данными хорошо соответствует требованиям.\n\n" \
                 "Готова обсудить детали в удобное для вас время."

        mock_response = _mock_anthropic_response(letter)

        with patch("capabilities.career_os.skills.cover_letter.generator.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(return_value=mock_response)

            with patch("capabilities.career_os.skills.cover_letter.generator.emit"):
                result = await __import__(
                    "capabilities.career_os.skills.cover_letter.generator",
                    fromlist=["generate_cover_letter"],
                ).generate_cover_letter(
                    vacancy_text="Product Manager нужен в tech компании.",
                    vacancy_id=1,
                    profile=_make_profile(),
                    score_reasons="- role: ✓ PM experience",
                    correlation_id="test-corr-id",
                )

        text, is_fb, in_tok, out_tok, cost = result
        assert text == letter
        assert is_fb is False
        assert in_tok == 200
        assert out_tok == 150
        assert cost > 0

    @pytest.mark.asyncio
    async def test_returns_fallback_on_llm_exception(self, tmp_path, monkeypatch):
        """On API exception, returns (fallback_text, True, 0, 0, 0.0)."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = ""

        example_path = tmp_path / "cover_letter_fallback.example.txt"
        example_path.write_text("Запасное письмо при ошибке LLM.", encoding="utf-8")
        real_path = tmp_path / "cover_letter_fallback.txt"
        mock_cfg = MagicMock()
        mock_cfg.cover_letter_fallback_path = str(real_path)
        mock_cfg.anthropic_api_key = "test-key"
        monkeypatch.setattr(gen, "config", mock_cfg)

        with patch("capabilities.career_os.skills.cover_letter.generator.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(side_effect=Exception("API error"))

            result = await gen.generate_cover_letter(
                vacancy_text="Тестовая вакансия",
                vacancy_id=2,
                profile=_make_profile(),
                score_reasons="",
                correlation_id="test-corr-2",
            )

        text, is_fb, in_tok, out_tok, cost = result
        assert is_fb is True
        assert in_tok == 0
        assert out_tok == 0
        assert cost == 0.0
        assert len(text) > 10

    @pytest.mark.asyncio
    async def test_returns_fallback_when_response_too_short(self, monkeypatch):
        """If LLM returns < 50 chars, fallback is used."""
        import capabilities.career_os.skills.cover_letter.generator as gen
        gen._fallback_cache = "Запасное письмо для короткого ответа LLM тест."

        mock_response = _mock_anthropic_response("Ок")  # way too short

        with patch("capabilities.career_os.skills.cover_letter.generator.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(return_value=mock_response)

            with patch("capabilities.career_os.skills.cover_letter.generator.emit"):
                result = await gen.generate_cover_letter(
                    vacancy_text="Вакансия PM",
                    vacancy_id=3,
                    profile=_make_profile(),
                    score_reasons="",
                    correlation_id="test-corr-3",
                )

        text, is_fb, in_tok, out_tok, cost = result
        assert is_fb is True
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_emits_llm_call_event_on_success(self, monkeypatch):
        """On successful LLM call, llm.call event is emitted."""
        letter = "A" * 100  # enough chars

        mock_response = _mock_anthropic_response(letter)
        emitted_events = []

        with patch("capabilities.career_os.skills.cover_letter.generator.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(return_value=mock_response)

            with patch(
                "capabilities.career_os.skills.cover_letter.generator.emit",
                side_effect=lambda name, payload, **kw: emitted_events.append(name),
            ):
                import capabilities.career_os.skills.cover_letter.generator as gen
                await gen.generate_cover_letter(
                    vacancy_text="PM vacancy test",
                    vacancy_id=4,
                    profile=_make_profile(),
                    score_reasons="",
                    correlation_id="test-corr-4",
                )

        assert "llm.call" in emitted_events

    @pytest.mark.asyncio
    async def test_sanitizes_vacancy_text(self, monkeypatch):
        """Vacancy text is sanitized (zero-width chars removed) before LLM call."""
        import capabilities.career_os.skills.cover_letter.generator as gen

        letter = "B" * 100
        mock_response = _mock_anthropic_response(letter)
        captured_messages = []

        def capture_create(**kwargs):
            captured_messages.append(kwargs["messages"][0]["content"])
            return mock_response

        with patch("capabilities.career_os.skills.cover_letter.generator.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(side_effect=capture_create)

            with patch("capabilities.career_os.skills.cover_letter.generator.emit"):
                await gen.generate_cover_letter(
                    vacancy_text="PM\u200b vacancy",  # zero-width space injection
                    vacancy_id=5,
                    profile=_make_profile(),
                    score_reasons="",
                    correlation_id="test-corr-5",
                )

        assert captured_messages
        assert "\u200b" not in captured_messages[0]
