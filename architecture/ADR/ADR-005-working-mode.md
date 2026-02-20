# ADR-005: Working Mode (Founder ↔ Chief Architect ↔ Claude Code)

**Status:** Accepted
**Date:** 2026-02-20
**Decider:** Founder + Chief Architect

## Decision

### Team Structure (final)

| Роль | Кто | Среда |
|------|-----|-------|
| **Founder / Business Owner** | Katerina | Claude.ai (этот чат) |
| **Chief Architect** | Claude Opus (этот агент) | Claude.ai project |
| **Implementation Agent (Tech Lead)** | Claude Code (VS Code extension) | VS Code terminal |
| **QA/Security Gate** | Claude Code (отдельный prompt) | VS Code terminal |

### Workflow per PR

```
1. Founder → Chief Architect (Claude.ai):
   "Founder brief: цель PR, ограничения, DoD"

2. Chief Architect → Founder:
   - PR plan (файлы, шаги, риски)
   - DoR / DoD checklist
   - Score contract / ADR if needed

3. Founder одобряет план

4. Chief Architect генерирует:
   a) Implementation task prompt (copy-paste → Claude Code)
   b) QA/Security gate prompt (copy-paste → Claude Code после implementation)
   c) PR review checklist

5. Founder в VS Code:
   - Создаёт ветку (pr3-assisted-scoring)
   - Copy-paste task prompts → Claude Code
   - Маленькие коммиты по подсистемам
   - После каждого шага: QA gate prompt

6. Founder → Chief Architect (Claude.ai):
   "PR done, review"
   Chief Architect делает final review по checklist

7. Founder: merge + push
```

### Commit Strategy for PR-3

Ветка: `pr3-assisted-scoring`

Коммиты (по порядку):
1. `chore: add architecture docs, ADRs, governance files`
2. `feat(core): migrations system + config + security baseline`
3. `feat(core): llm client abstraction + sanitization + schemas`
4. `feat(career_os): scoring worker skeleton + idempotency`
5. `feat(career_os): scoring skill + prompt + profile model`
6. `test: scoring unit tests + fixtures`
7. `feat(telegram): integrate worker + notification flow`
8. `docs: update STATUS, DECISIONS, CHANGELOG`

### Review Gates

После шагов 2, 3, 5, 7 — Founder запускает QA gate prompt в Claude Code.
После шага 8 — Chief Architect делает full review.

## Consequences

- Chief Architect готовит полные task prompts (copy-paste ready)
- QA — не отдельный человек, а отдельный prompt/pass в Claude Code
- Security review встроен в QA gate
- Founder контролирует flow, не пишет код
