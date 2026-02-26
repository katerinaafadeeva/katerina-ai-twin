import json
import logging
import re
import time

import anthropic

from core.config import config
from core.events import emit
from core.llm.schemas import LLMCallRecord, ScoringOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    # cost per 1M tokens (input / output)
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# FALLBACK_MODEL is used by the scoring handler (handler.py) for retry logic.
# call_llm_scoring() is a single-model transport function — retry is the
# caller's responsibility (see capabilities/career_os/skills/match_scoring/handler.py).
FALLBACK_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

def _extract_json(text: str) -> str:
    """Extract JSON from LLM output robustly.

    Handles:
      - raw JSON
      - fenced blocks ```json ... ``` (closed)
      - fenced blocks without closing ``` (some models do this)
      - extra prose around JSON (best-effort by slicing {...})

    Raises ValueError if we can't confidently locate a JSON object.
    """
    if not text:
        raise ValueError("Empty LLM output")

    s = text.strip()

    # 1) Prefer a closed fenced block if present
    m = _CODE_FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    else:
        # 2) Handle an *unclosed* fence: starts with ``` or ```json
        if s.startswith("```"):
            # drop first line (``` or ```json)
            nl = s.find("\n")
            if nl != -1:
                s = s[nl + 1 :].strip()
            # if it still contains a closing fence later, drop it
            end = s.rfind("```")
            if end != -1:
                s = s[:end].strip()

    # 3) If the string isn't a JSON object, try to slice from first { to last }
    if not s.startswith("{"):
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1].strip()

    if not s.startswith("{"):
        raise ValueError(f"LLM output does not look like JSON: {text[:100]!r}")

    return s


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def call_llm_scoring(
    system_prompt: str,
    user_message: str,
    prompt_version: str,
    job_raw_id: int,
    correlation_id: str,
    model: str = DEFAULT_MODEL,
) -> ScoringOutput:
    """Call Anthropic API for vacancy scoring. Validates output. Emits audit event.

    Single-model transport function — no retry/fallback logic here.
    If this raises, the caller (handler.py) decides whether to retry with FALLBACK_MODEL.

    Args:
        system_prompt: System message (from prompts/scoring_v1.py).
        user_message: User message with profile + vacancy text.
        prompt_version: Version string for audit log (e.g. "scoring_v1").
        job_raw_id: DB id of the vacancy being scored (for audit log).
        correlation_id: UUID linking all events for one scoring attempt.
        model: Anthropic model ID. Defaults to DEFAULT_MODEL.

    Returns:
        Validated ScoringOutput.

    Raises:
        json.JSONDecodeError: LLM returned non-JSON.
        pydantic.ValidationError: JSON valid but schema mismatch.
        ValueError: JSON extraction failed (code fence stripping issue).
        anthropic.APIError: API-level failure.
    """
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    start = time.monotonic()
    success = False
    validation_passed = False
    input_tokens = 0
    output_tokens = 0

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=900,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        raw_text = response.content[0].text

        json_text = _extract_json(raw_text)
        parsed = json.loads(json_text)
        result = ScoringOutput(**parsed)

        validation_passed = True
        success = True
        return result

    except Exception:
        logger.warning(
            "LLM scoring call failed",
            extra={"model": model, "job_raw_id": job_raw_id},
            exc_info=True,
        )
        raise

    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (
            input_tokens * pricing["input"] + output_tokens * pricing["output"]
        ) / 1_000_000

        record = LLMCallRecord(
            task="vacancy_scoring",
            model=model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            duration_ms=duration_ms,
            success=success,
            validation_passed=validation_passed,
            job_raw_id=job_raw_id,
        )
        try:
            emit(
                "llm.call",
                record.model_dump(),
                actor="scoring_worker",
                correlation_id=correlation_id,
            )
        except Exception:
            # Audit failure must never mask the original exception
            logger.exception("Failed to emit llm.call audit event")
