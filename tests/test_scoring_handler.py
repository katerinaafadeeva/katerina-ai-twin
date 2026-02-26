"""Tests for capabilities/career_os/skills/match_scoring/handler.py.

Covers:
- _load_resume: missing file returns empty string (graceful fallback)
- _load_resume: reads file content up to 20000 chars
- _load_resume: mtime-based cache — re-reads when mtime changes
- _load_resume: does NOT re-read when mtime is unchanged
- score_vacancy_llm: resume text included in user_message sent to LLM
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _load_resume — unit tests
# ---------------------------------------------------------------------------


class TestLoadResume:
    def setup_method(self):
        """Reset module-level cache before each test."""
        import capabilities.career_os.skills.match_scoring.handler as h
        h._resume_cache = ("", None)

    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        """Missing resume file → empty string, no exception."""
        import capabilities.career_os.skills.match_scoring.handler as h
        mock_cfg = MagicMock()
        mock_cfg.resume_path = str(tmp_path / "nonexistent_resume.md")
        monkeypatch.setattr(h, "config", mock_cfg)

        result = h._load_resume()

        assert result == ""

    def test_reads_file_content(self, tmp_path, monkeypatch):
        """Existing file → content returned."""
        import capabilities.career_os.skills.match_scoring.handler as h
        resume_file = tmp_path / "resume.md"
        resume_file.write_text("# Katerina\n\nProduct Manager, 7 years.", encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.resume_path = str(resume_file)
        monkeypatch.setattr(h, "config", mock_cfg)

        result = h._load_resume()

        assert "Product Manager" in result
        assert "Katerina" in result

    def test_truncates_to_20000_chars(self, tmp_path, monkeypatch):
        """Content longer than 20000 chars is truncated."""
        import capabilities.career_os.skills.match_scoring.handler as h
        resume_file = tmp_path / "resume.md"
        resume_file.write_text("x" * 25_000, encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.resume_path = str(resume_file)
        monkeypatch.setattr(h, "config", mock_cfg)

        result = h._load_resume()

        assert len(result) == 20_000

    def test_cache_avoids_reread_when_mtime_unchanged(self, tmp_path, monkeypatch):
        """Same mtime → cached content returned without re-opening file."""
        import capabilities.career_os.skills.match_scoring.handler as h
        resume_file = tmp_path / "resume.md"
        resume_file.write_text("First content", encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.resume_path = str(resume_file)
        monkeypatch.setattr(h, "config", mock_cfg)

        first = h._load_resume()

        # Overwrite content but preserve mtime (simulate unchanged mtime)
        mtime = os.path.getmtime(str(resume_file))
        resume_file.write_text("Changed content", encoding="utf-8")
        os.utime(str(resume_file), (mtime, mtime))

        second = h._load_resume()

        assert first == second == "First content"

    def test_cache_refreshes_when_mtime_changes(self, tmp_path, monkeypatch):
        """Different mtime → file re-read, new content returned."""
        import capabilities.career_os.skills.match_scoring.handler as h
        resume_file = tmp_path / "resume.md"
        resume_file.write_text("Original", encoding="utf-8")

        mock_cfg = MagicMock()
        mock_cfg.resume_path = str(resume_file)
        monkeypatch.setattr(h, "config", mock_cfg)

        first = h._load_resume()
        assert first == "Original"

        # Write new content and advance mtime
        resume_file.write_text("Updated", encoding="utf-8")
        new_mtime = os.path.getmtime(str(resume_file)) + 1
        os.utime(str(resume_file), (new_mtime, new_mtime))

        second = h._load_resume()
        assert second == "Updated"


# ---------------------------------------------------------------------------
# score_vacancy_llm — resume injected into prompt
# ---------------------------------------------------------------------------


class TestScoreVacancyLlmIncludesResume:
    @pytest.mark.asyncio
    async def test_resume_text_included_in_user_message(self, monkeypatch, sample_profile):
        """score_vacancy_llm must include resume_text in the user message sent to LLM."""
        import capabilities.career_os.skills.match_scoring.handler as h

        # Reset cache
        h._resume_cache = ("", None)

        resume_content = "PM with 7 years experience at Yandex"

        mock_cfg = MagicMock()
        mock_cfg.resume_path = "/fake/resume.md"
        monkeypatch.setattr(h, "config", mock_cfg)

        # Patch _load_resume to return controlled content
        monkeypatch.setattr(h, "_load_resume", lambda: resume_content)

        captured_messages = []

        async def mock_call_llm(system_prompt, user_message, **kwargs):
            captured_messages.append(user_message)
            from core.llm.schemas import ScoreReason, ScoringOutput
            return ScoringOutput(
                score=7,
                reasons=[ScoreReason(criterion="role_match", matched=True, note="ok")],
                explanation="Хорошее совпадение по роли.",
            )

        monkeypatch.setattr(h, "call_llm_scoring", mock_call_llm)

        await h.score_vacancy_llm(
            vacancy_text="Product Manager в Яндекс",
            vacancy_id=1,
            profile=sample_profile,
            correlation_id="test-corr",
        )

        assert len(captured_messages) == 1
        assert resume_content in captured_messages[0]

    @pytest.mark.asyncio
    async def test_fallback_text_when_resume_missing(self, monkeypatch, sample_profile):
        """When resume is missing, prompt contains fallback placeholder."""
        import capabilities.career_os.skills.match_scoring.handler as h

        h._resume_cache = ("", None)
        monkeypatch.setattr(h, "_load_resume", lambda: "")

        captured_messages = []

        async def mock_call_llm(system_prompt, user_message, **kwargs):
            captured_messages.append(user_message)
            from core.llm.schemas import ScoreReason, ScoringOutput
            return ScoringOutput(
                score=5,
                reasons=[ScoreReason(criterion="role_match", matched=True, note="ok")],
                explanation="Нормальное совпадение по роли.",
            )

        monkeypatch.setattr(h, "call_llm_scoring", mock_call_llm)

        await h.score_vacancy_llm(
            vacancy_text="Some vacancy",
            vacancy_id=2,
            profile=sample_profile,
            correlation_id="test-corr-2",
        )

        assert "(резюме не предоставлено)" in captured_messages[0]
