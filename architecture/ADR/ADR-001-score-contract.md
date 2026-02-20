# ADR-001: Score Contract

**Status:** Accepted
**Date:** 2026-02-20
**Decider:** Chief Architect + Founder

## Context

Несколько документов ссылаются на score шкалу, но формальный контракт не зафиксирован.
Необходимо определить range, тип хранения, семантику порогов и edge cases.

### Источники (source of truth audit)

| Документ | Что указано |
|----------|-------------|
| DECISIONS.md | `Score scale: 0..10`, `<5 ignore`, `5..7 auto-send`, `>7 approval + cover` |
| BACKLOG.md | `heuristic scorer 0..10` |
| DDL (policy) | `threshold_low INTEGER DEFAULT 5`, `threshold_high INTEGER DEFAULT 7` |
| CHAT_SNAPSHOT.md | `Score 0..10`, пороги совпадают |

### Проблемы

1. Тип `INTEGER` для порогов, но score может быть дробным (7.3 vs 7.8 — это разные уровни)
2. Граничные значения неоднозначны: `5..7` включает 5 и 7? `>7` — это строго 7.01+ или 8+?
3. REAL vs INTEGER для самого score не зафиксирован

## Decision

### Score Value Contract

| Параметр | Значение |
|----------|----------|
| Range | **0..10 inclusive** |
| Storage type | **INTEGER (0–100 internal)** |
| Display type | **"7.3" (divided by 10 for display)** |
| Precision | 1 decimal place |

**Обоснование:** INTEGER хранение (0–100) вместо REAL:
- Нет проблем с floating point comparison (7.0 == 7.0 всегда)
- Сортировка и пороги работают точно
- Отображение: `score / 10` → "7.3"
- Пороги в policy хранятся так же: threshold_low=50, threshold_high=70

### Threshold Semantics

```
score < threshold_low (50):    → IGNORE (не показывать)
threshold_low ≤ score ≤ threshold_high (50..70):  → AUTO_QUEUE (auto-send within daily limit)
score > threshold_high (70):   → APPROVAL_REQUIRED (показать + cover letter)
```

- Граничные значения: **inclusive** для диапазона auto (50 входит в auto, 70 входит в auto)
- `> threshold_high` — **строго больше** (71+)

### Score Reasons

```json
{
  "score": 73,
  "reasons": [
    {"criterion": "role_match", "matched": true, "note": "Product Manager — прямое совпадение"},
    {"criterion": "salary_fit", "matched": true, "note": "300k ≥ 250k floor"},
    {"criterion": "format_ok", "matched": true, "note": "remote"},
    {"criterion": "negative_signals", "matched": false, "note": "нет негативных сигналов"}
  ],
  "explanation": "Сильное совпадение: роль PM, удалёнка, зарплата выше минимума. Рекомендую рассмотреть.",
  "model": "claude-haiku",
  "prompt_version": "scoring_v1"
}
```

## Consequences

- Миграция policy: threshold_low → 50, threshold_high → 70 (×10)
- job_scores.score: INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100)
- Display layer делит на 10
- LLM prompt должен запрашивать score в range 0–100 (or 0.0–10.0 с mapping)
