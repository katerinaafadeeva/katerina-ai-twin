"""Tests for core/llm/prompts/cover_letter_v1.py.

Covers:
- SYSTEM_PROMPT contains prompt injection defence
- SYSTEM_PROMPT has <resume> tag reference
- SYSTEM_PROMPT mentions language detection (RU/EN)
- SYSTEM_PROMPT specifies character-based length (400-500)
- USER_TEMPLATE has all four required placeholders (including resume_text)
- PROMPT_VERSION is defined as "cover_letter_v2"
- Template renders without KeyError
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

    def test_contains_resume_tag_reference(self):
        """New: prompt must reference <resume> tag."""
        assert "<resume>" in SYSTEM_PROMPT

    def test_mentions_language_detection(self):
        """New: prompt must instruct LLM to detect vacancy language."""
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "detect" in prompt_lower or "language" in prompt_lower

    def test_specifies_russian_option(self):
        """Russian is one of the language options."""
        assert "Russian" in SYSTEM_PROMPT

    def test_prohibits_salary_in_letter(self):
        assert "salary" in SYSTEM_PROMPT.lower()

    def test_specifies_character_length(self):
        """New: prompt must mention characters (not words) as the length unit."""
        assert "400" in SYSTEM_PROMPT or "500" in SYSTEM_PROMPT
        assert "CHARACTERS" in SYSTEM_PROMPT or "characters" in SYSTEM_PROMPT.lower()

    def test_non_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_prohibits_inventing_experience(self):
        """New: prompt must prohibit inventing experience not in resume."""
        assert "invent" in SYSTEM_PROMPT.lower()


class TestUserTemplate:
    def test_has_profile_placeholder(self):
        assert "{profile_json}" in USER_TEMPLATE

    def test_has_vacancy_placeholder(self):
        assert "{vacancy_text}" in USER_TEMPLATE

    def test_has_reasons_placeholder(self):
        assert "{reasons_text}" in USER_TEMPLATE

    def test_has_resume_placeholder(self):
        """New: template must include resume_text placeholder."""
        assert "{resume_text}" in USER_TEMPLATE

    def test_renders_without_key_error(self):
        """All four placeholders provided → no KeyError."""
        rendered = USER_TEMPLATE.format(
            profile_json='{"target_roles": ["PM"]}',
            vacancy_text="Требуется Product Manager",
            reasons_text="- role: ✓ PM experience",
            resume_text="PM with 5 years at Yandex",
        )
        assert "Product Manager" in rendered
        assert "PM experience" in rendered
        assert "Yandex" in rendered

    def test_wraps_vacancy_in_tags(self):
        assert "<vacancy>" in USER_TEMPLATE
        assert "</vacancy>" in USER_TEMPLATE

    def test_wraps_profile_in_tags(self):
        assert "<profile>" in USER_TEMPLATE
        assert "</profile>" in USER_TEMPLATE

    def test_wraps_resume_in_tags(self):
        """New: resume content must be wrapped in <resume> tags."""
        assert "<resume>" in USER_TEMPLATE
        assert "</resume>" in USER_TEMPLATE


class TestPromptVersion:
    def test_prompt_version_defined(self):
        assert PROMPT_VERSION

    def test_prompt_version_is_string(self):
        assert isinstance(PROMPT_VERSION, str)

    def test_prompt_version_starts_with_cover_letter(self):
        assert PROMPT_VERSION.startswith("cover_letter")

    def test_prompt_version_is_v2(self):
        """New prompt must be versioned as v2."""
        assert PROMPT_VERSION == "cover_letter_v2"
