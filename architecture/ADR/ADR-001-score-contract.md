# ADR-001: Score Contract

**Status:** Accepted (revised 2026-02-19 — previous 0–100 approach rejected)
**Date:** 2026-02-19
**Decider:** Katerina (Founder)

## Context

DECISIONS.md (source of truth, написан основателем) устанавливает: `Score scale: 0..10`.
Предыдущая версия этого ADR предлагала хранить score как INTEGER 0–100 с display-слоем `/10`.
Это решение **отклонено** как излишне сложное и противоречащее DECISIONS.md.

## Decision

### Score Value Contract

| Параметр | Значение |
|---|---|
| Range | **0..10 inclusive** |
| Storage type | **INTEGER** |
| Display | `"{score}/10"` — без конверсии |
| Precision | Целые числа (0, 1, 2 … 10) |

**Почему не 0–100:**
- Добавляет скрытую сложность (display-слой `/10` везде)
- DECISIONS.md явно 0..10 — расхождение недопустимо
- Пороги 5 и 7 читаемы без мысленного умножения
- 11 уровней достаточно для задачи

### Threshold Semantics

```
score < 5         → IGNORE
5 ≤ score ≤ 7     → AUTO_QUEUE (авто-отправка в рамках daily_limit)
score > 7         → APPROVAL_REQUIRED (показать + cover letter)
```

Граничные значения: inclusive для AUTO_QUEUE (5 входит, 7 входит). `> 7` — строго (8+).

### DB Schema

```sql
-- policy (migration 001 defaults — не требует изменений):
threshold_low   INTEGER DEFAULT 5
threshold_high  INTEGER DEFAULT 7

-- job_scores:
score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10)
```

### Score Emojis

| Score | Emoji |
|---|---|
| ≥ 7 | 🟢 |
| 5–6 | 🟡 |
| < 5 | 🔴 |

### Score Output Example

```json
{
  "score": 8,
  "reasons": [
    {"criterion": "role_match",       "matched": true,  "note": "Product Manager — прямое совпадение"},
    {"criterion": "salary_fit",       "matched": true,  "note": "300k ≥ 250k floor"},
    {"criterion": "format_match",     "matched": true,  "note": "remote"},
    {"criterion": "negative_signals", "matched": false, "note": "нет негативных сигналов"}
  ],
  "explanation": "Сильное совпадение: роль PM, удалёнка, зарплата выше минимума.",
  "model": "claude-haiku-4-5-20251001",
  "prompt_version": "scoring_v1"
}
```

## Consequences

- LLM prompt: score в диапазоне **0–10**
- Pydantic: `score: int = Field(ge=0, le=10)`
- Worker: `_score_emoji` с порогами `>= 7` и `>= 5`
- Telegram: `f"{score}/10"` без деления
- Migration 004 (threshold scale ×10) не нужна и удалена
