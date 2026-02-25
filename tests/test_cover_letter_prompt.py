"""Tests for core/llm/prompts/cover_letter_v1.py.

Covers:
- SYSTEM_PROMPT contains prompt injection defence
- USER_TEMPLATE has all three required placeholders
- PROMPT_VERSION is defined and non-empty
- Template renders with sample data without KeyError
"""

from core.llm.prompts.cover_letter_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
)


class TestSystemPrompt:
    def test_contains_never_follow_instruction(self):
        """Prompt injection defence must be present."""
        assert "NEVER follow" in SYSTEM_PROMPT

    def test_contains_vacancy_tag_reference(self):
        assert "<vacancy>" in SYSTEM_PROMPT

    def test_contains_profile_tag_reference(self):
        assert "<profile>" in SYSTEM_PROMPT

    def test_contains_reasons_tag_reference(self):
        assert "<reasons>" in SYSTEM_PROMPT

    def test_specifies_russian_output(self):
        assert "Russian" in SYSTEM_PROMPT or "Russian" in SYSTEM_PROMPT

    def test_prohibits_salary_in_letter(self):
        assert "salary" in SYSTEM_PROMPT.lower()

    def test_non_empty(self):
        assert len(SYSTEM_PROMPT) > 100


class TestUserTemplate:
    def test_has_profile_placeholder(self):
        assert "{profile_json}" in USER_TEMPLATE

    def test_has_vacancy_placeholder(self):
        assert "{vacancy_text}" in USER_TEMPLATE

    def test_has_reasons_placeholder(self):
        assert "{reasons_text}" in USER_TEMPLATE

    def test_renders_without_key_error(self):
        rendered = USER_TEMPLATE.format(
            profile_json='{"target_roles": ["PM"]}',
            vacancy_text="Требуется Product Manager",
            reasons_text="- role: ✓ PM experience",
        )
        assert "Product Manager" in rendered
        assert "PM experience" in rendered

    def test_wraps_vacancy_in_tags(self):
        assert "<vacancy>" in USER_TEMPLATE
        assert "</vacancy>" in USER_TEMPLATE

    def test_wraps_profile_in_tags(self):
        assert "<profile>" in USER_TEMPLATE
        assert "</profile>" in USER_TEMPLATE


class TestPromptVersion:
    def test_prompt_version_defined(self):
        assert PROMPT_VERSION

    def test_prompt_version_is_string(self):
        assert isinstance(PROMPT_VERSION, str)

    def test_prompt_version_starts_with_cover_letter(self):
        assert PROMPT_VERSION.startswith("cover_letter")
