MVP v1 Closure Plan
Career OS — Katerina AI Twin
Технический аудит main ветки и план закрытия

Дата: 02 марта 2026
Автор: Chief Architect (Claude Opus)
Для: Tech Lead (Claude Code)

1. Executive Summary

MVP v1 Career OS покрывает полный end-to-end pipeline:

HH Ingest → Scoring → Policy → Cover Letter → Auto-Apply.

Все 8 PR (PR-1…PR-8) вмержены в main.
293 теста — все зелёные.

Аудит выявил:

5 блокеров (P0)

7 важных задач (P1)

8 улучшений (P2)

Главные проблемы:

отсутствует schedule-based запуск auto-apply (будни / рабочее время МСК)

расхождение threshold_high между DECISIONS.md и ADR-001

неполная реализация Telegram forward scoring

отсутствует команда /apply

После устранения P0 система готова к продакшн-запуску в safe mode.
| PR   | Scope                                 | Статус | Примечания                  |
| ---- | ------------------------------------- | ------ | --------------------------- |
| PR-1 | Foundation: SQLite schema, migrations | ✅ DONE | Без замечаний               |
| PR-2 | Telegram Ingest                       | ✅ DONE | Forward → job_raw → scoring |
| PR-3 | LLM Scoring                           | ✅ DONE | 41 тест                     |
| PR-4 | Policy Engine                         | ✅ DONE | 54 теста                    |
| PR-5 | Telegram Approval UX                  | ✅ DONE | 35 тестов                   |
| PR-6 | HH Ingest v0.1                        | ✅ DONE | 70 тестов                   |
| PR-7 | Cover Letter                          | ✅ DONE | 40 тестов                   |
| PR-8 | Playwright Auto-Apply                 | ✅ DONE | 49 тестов                   |

Итого: 293 теста. Полный pipeline реализован.

3. Полностью реализовано
3.1 Scoring Pipeline

Claude Haiku + fallback Sonnet

Pydantic-валидация

Pre-filter без LLM

Advanced filters (salary floor, keywords)

Daily cap (emit-first durability)

Resume auto-reload

PII redaction

3.2 Policy Engine

IGNORE / AUTO_QUEUE / AUTO_APPLY / HOLD / APPROVAL_REQUIRED

Source-aware routing

Daily limit

HOLD summary

Deterministic routing

3.3 Cover Letter Generation

Claude Haiku

Negative phrase guardrail

Length retry

Fallback chain

Daily cap

Resume integration

3.4 Auto-Apply (Playwright)

4 пути вставки письма:

A — Popup

B — Inline

C — Post-apply

D — Chat

6 outcomes:

DONE

ALREADY_APPLIED

MANUAL_REQUIRED

CAPTCHA

SESSION_EXPIRED

FAILED

Дополнительно:

apply_runs отделён от actions

JIT cover letter generation

Anti-ban delays

Telemetry

Failure artifacts

3.5 Telegram Interface

Команды:

/start

/today

/limits

/stats

/hh_login

/resume_apply

Inline approve/reject/snooze.

Forward handler работает.

3.6 Security & Audit

Telegram whitelist

Input sanitization

Prompt injection defence

LLM audit

Event system (append-only)

4. Частично реализовано
4.1 Schedule-based Auto-Apply

❌ Не реализовано.

Worker работает 24/7.

Нужно:

Проверка будней

Проверка времени (MSK)

Configurable hours

4.2 Команда /apply

❌ Не зарегистрирована.

Есть /resume_apply, но нет /apply.

4.3 Telegram Forward Scoring

Cover letter не генерируется для AUTO_QUEUE (TG source score 5-6).

4.4 Полный текст сопроводительного в TG

Для AUTO_APPLY текст не показывается.

4.5 Различение HH сценариев в уведомлениях

manual_required не содержит score и причину.

5. Не реализовано

/apply

Schedule logic

/help

Полный UX для TG forward

6. Архитектурный аудит
6.1 Threshold mismatch

DECISIONS.md: score >= 7 → APPROVAL_REQUIRED
ADR-001: score > 7 → APPROVAL_REQUIRED

Код соответствует DECISIONS.md.
ADR-001 нужно обновить.

6.2 Policy as Data

_NEGATIVE_PATTERNS захардкожен

часть лимитов не hot-reload

6.3 Overengineering apply_flow.py

580+ строк.

Для MVP можно упростить до:

Popup

Inline

MANUAL_REQUIRED fallback

6.4 UTC vs MSK

date('now') использует UTC.

Daily caps могут сбрасываться в 03:00 МСК.

7. Баги

scorer_version naming mismatch (не критично)

UTC reset UX

Минимальный /start

Нет graceful shutdown
8. Задачи для TL
P0 — Блокеры
Код	Задача
T-01	Добавить /apply
T-02	Реализовать schedule (будни + MSK)
T-03	Исправить ADR-001
T-04	Улучшить /start + добавить /help
T-05	manual_required: добавить score + причину
P1 — Качество

Cover letter для TG forward

Показывать письмо в AUTO_APPLY

Проверить селекторы C/D

Обновить ADR-002 и ADR-004

Graceful shutdown

Ссылка во всех уведомлениях

Доп. защита от false DONE

P2 — v1.1

TZ-aware caps

Вынести negative patterns в config

Оптимизировать DB connections

Упростить apply_flow

Audit IGNORE

Docker

Screenshot в TG

Retention policy

9. Safe Mode для запуска

Рекомендуемая конфигурация:

APPLY_DAILY_CAP=5
APPLY_DELAY_MIN=15
APPLY_DELAY_MAX=45
APPLY_BATCH_SIZE=3

Постепенное увеличение после недели мониторинга.

10. Обновление документации

Обновить ADR-001

Обновить ADR-002

Обновить ADR-004

Обновить SYSTEM_OVERVIEW.md

Добавить DEPLOYMENT.md

Обновить BACKLOG.md
| Риск              | Severity | Mitigation         |
| ----------------- | -------- | ------------------ |
| HH UI change      | High     | selectors.py       |
| Session expire    | Medium   | notify + /hh_login |
| IP ban            | Medium   | safe mode          |
| LLM hallucination | Low      | approval required  |
| SQLite corruption | Low      | backup             |
12. Чеклист запуска

P0 выполнены

pytest зелёный

Safe-mode config применён

Smoke test выполнен

3 дня стабильности → увеличить cap