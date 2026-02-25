from typing import List, Optional

from pydantic import BaseModel, Field


class ScoreReason(BaseModel):
    criterion: str
    matched: bool
    note: str  # Russian, short


class ScoringOutput(BaseModel):
    score: int = Field(ge=0, le=10)
    reasons: List[ScoreReason] = Field(min_length=1)
    explanation: str = Field(min_length=10, max_length=500)


class CoverLetterOutput(BaseModel):
    """Validated cover letter output — simple length check."""
    letter_text: str = Field(min_length=50, max_length=2000)


class LLMCallRecord(BaseModel):
    """Audit record for each LLM call. Written to events table."""

    task: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    success: bool
    validation_passed: bool
    job_raw_id: Optional[int] = None
