# ADR-002: LLM-Assisted Scoring (не heuristic-only)

**Status:** Accepted
**Date:** 2026-02-20
**Decider:** Founder (Katerina) — business requirement

## Context

Первоначальный план (Chief Architect Report v1) предполагал heuristic-only scoring до PR-7.
Founder корректирует: **assisted scoring с LLM в PR-3**.

### Founder rationale

- Heuristic scoring на text matching даёт слабое качество для русскоязычных вакансий (склонения, синонимы, описательные формулировки)
- Ценность продукта — в quality of scoring. Плохой scoring = нулевая полезность.
- LLM-assisted scoring — осознанный выбор с Day 1 Career OS
- Cost допустим при правильных ограничениях

## Decision

### Scoring Architecture: Hybrid (LLM-assisted)

```
vacancy.ingested event
    ↓
Worker picks up event
    ↓
Pre-processing (sanitize, truncate, redact PII)
    ↓
LLM call: structured output (score + reasons + explanation)
    ↓
Validate output (schema, range, required fields)
    ↓
Persist to job_scores
    ↓
Emit vacancy.scored event
```

### Model Policy

| Параметр | Значение |
|----------|----------|
| Model | claude-haiku-4-5 (cheapest capable) |
| Fallback | claude-sonnet-4-5 (if haiku fails validation) |
| Max tokens input | ~500 (truncated vacancy text) |
| Max tokens output | ~300 |
| Temperature | 0 (deterministic) |
| Response format | JSON (structured output) |
| Cache | Hash-based, TTL 24h |

### Cost Estimate

- ~50 vacancies/day × ~800 tokens/call ≈ 40K tokens/day
- Claude Haiku: ~$0.03/day ≈ $1/month
- Допустимо.

### What LLM does vs what it doesn't

| LLM делает | LLM НЕ делает |
|-----------|---------------|
| Оценивает релевантность вакансии профилю | Не принимает решений (apply/reject) |
| Генерирует explanation (1-2 предложения, RU) | Не видит персональные данные (salary expectations редактируются) |
| Извлекает structured fields (role, company, format) | Не делает chain-of-thought с другими LLM |
| Присваивает score 0-100 | Не имеет доступа к actions/policy |

## Consequences

- PR-3 включает LLM client abstraction
- PR-3 включает prompt injection defense
- PR-3 включает LLM audit logging
- PR-3 включает PII redaction layer
- Cost tracking обязателен с Day 1
- Token budget policy распространяется на scoring
