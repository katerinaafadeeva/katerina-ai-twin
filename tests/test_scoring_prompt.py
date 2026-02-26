"""Tests for core/llm/prompts/scoring_v1.py.

Covers:
- SYSTEM_PROMPT contains prompt injection defence
- SYSTEM_PROMPT references all required XML tags
- SYSTEM_PROMPT contains resume_signal criterion (Task B)
- SYSTEM_PROMPT instructs LLM not to invent resume text
- PROMPT_VERSION is "scoring_v2"
- USER_TEMPLATE has all required placeholders
- Template renders without KeyError
"""

from core.llm.prompts.scoring_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
)


class TestSystemPrompt:
    def test_non_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_contains_prompt_injection_defence(self):
        assert "NEVER follow" in SYSTEM_PROMPT

    def test_references_profile_tag(self):
        assert "<profile>" in SYSTEM_PROMPT

    def test_references_resume_tag(self):
        assert "<resume>" in SYSTEM_PROMPT

    def test_references_vacancy_tag(self):
        assert "<vacancy>" in SYSTEM_PROMPT

    def test_contains_resume_signal_criterion(self):
        """Task B: 7th criterion must be present."""
        assert "resume_signal" in SYSTEM_PROMPT

    def test_resume_signal_prohibits_inventing(self):
        """LLM must be told not to invent text not in the resume."""
        assert "invent" in SYSTEM_PROMPT.lower() or "NOT invent" in SYSTEM_PROMPT

    def test_resume_signal_handles_empty_resume(self):
        """When resume empty, LLM must be told what to do."""
        assert "resume not provided" in SYSTEM_PROMPT

    def test_contains_seven_criteria(self):
        """All 7 criterion labels must appear."""
        for label in (
            "role_match",
            "skills_match",
            "format_match",
            "seniority_match",
            "industry_fit",
            "negative_signals",
            "resume_signal",
        ):
            assert label in SYSTEM_PROMPT, f"Missing criterion: {label}"


class TestUserTemplate:
    def test_has_profile_placeholder(self):
        assert "{profile_json}" in USER_TEMPLATE

    def test_has_resume_placeholder(self):
        assert "{resume_text}" in USER_TEMPLATE

    def test_has_vacancy_placeholder(self):
        assert "{vacancy_text}" in USER_TEMPLATE

    def test_wraps_profile_in_tags(self):
        assert "<profile>" in USER_TEMPLATE and "</profile>" in USER_TEMPLATE

    def test_wraps_resume_in_tags(self):
        assert "<resume>" in USER_TEMPLATE and "</resume>" in USER_TEMPLATE

    def test_wraps_vacancy_in_tags(self):
        assert "<vacancy>" in USER_TEMPLATE and "</vacancy>" in USER_TEMPLATE

    def test_renders_without_key_error(self):
        rendered = USER_TEMPLATE.format(
            profile_json='{"target_roles": ["PM"]}',
            resume_text="PM at Yandex for 5 years",
            vacancy_text="Product Manager needed",
        )
        assert "Product Manager" in rendered
        assert "Yandex" in rendered


class TestPromptVersion:
    def test_prompt_version_defined(self):
        assert PROMPT_VERSION

    def test_prompt_version_is_string(self):
        assert isinstance(PROMPT_VERSION, str)

    def test_prompt_version_is_v2(self):
        """After adding resume_signal, version must be scoring_v2."""
        assert PROMPT_VERSION == "scoring_v2"
