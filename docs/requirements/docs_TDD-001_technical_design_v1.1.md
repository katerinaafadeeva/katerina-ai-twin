# Career OS — Техническая спецификация MVP v1

**Документ:** TDD-001  
**Версия:** 1.1  
**Дата:** 13 марта 2026  
**Автор:** Opus (системный аналитик)  
**Связан с:** BRD-001 v1.1  
**Статус:** НА СОГЛАСОВАНИИ  

---

## 1. Архитектура системы

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram Bot (UI)                     │
│  Commands / Callbacks / Forward handler                  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              Background Workers (asyncio tasks)          │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ HH Ingest    │  │ Scoring      │  │ Apply Worker  │ │
│  │ (30 min)     │  │ (2 min)      │  │ (2-5 min)     │ │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘ │
└─────────┼─────────────────┼───────────────────┼─────────┘
          │                 │                   │
┌─────────▼─────────────────▼───────────────────▼─────────┐
│  SQLite: job_raw → job_scores → actions → apply_runs    │
│                                    └→ cover_letters     │
└─────────────────────────────────────────────────────────┘
          │                 │                   │
┌─────────▼─────────────────▼───────────────────▼─────────┐
│  HH.ru API (ingest) | Anthropic API (Haiku) | Playwright │
└─────────────────────────────────────────────────────────┘
```

### 1.1. Файловая структура

```
katerina-ai-twin/
├── capabilities/career_os/skills/
│   ├── match_scoring/      # Scoring worker + store + pre-filter
│   ├── hh_apply/           # Apply worker + store + notifier
│   ├── apply_policy/       # Policy engine
│   ├── cover_letter/       # Cover letter generation
│   ├── vacancy_ingest_hh/  # HH API ingest
│   └── link_extractor/     # NEW: извлечение ссылок из TG [FR-SRC-03]
├── connectors/
│   ├── telegram_bot.py     # Bot entry + handlers
│   └── hh_browser/         # Playwright apply
├── control_plane/handlers.py  # Approve/reject callbacks
├── core/
│   ├── config.py           # Env config
│   ├── db.py               # SQLite
│   ├── llm/client.py       # Anthropic API + prompt caching
│   └── migrations/
├── docs/
│   └── requirements/       # BRD-001, TDD-001
├── identity/resume.md      # Resume
├── tests/
├── data/career.db          # NOT in git
└── .env                    # NOT in git
```

---

## 2. Data Model

### 2.1. ERD

```
job_raw (1) ──── (0..1) job_scores
   │
   └──── (0..1) actions (1) ──── (0..*) apply_runs
                    │
                    └──── (0..1) cover_letters
```

### 2.2. Таблицы

#### job_raw

| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | |
| source | TEXT | `hh_api` / `telegram_forward` |
| hh_vacancy_id | TEXT | ID на HH (NULL для TG без HH-ссылки) |
| raw_text | TEXT | Полный текст |
| extracted_url | TEXT | NEW: URL из которого извлечено полное описание |
| created_at | TIMESTAMP | |

#### job_scores

| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | |
| job_raw_id | INTEGER FK | |
| score | INTEGER | 1-10 |
| scorer_version | TEXT | `scoring_v1` |
| scored_at | TIMESTAMP | |

#### actions

| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | |
| job_raw_id | INTEGER FK | |
| action_type | TEXT | IGNORE / AUTO_APPLY / AUTO_QUEUE / APPROVAL_REQUIRED / HOLD |
| status | TEXT | pending / approved / rejected / applied / skipped / hold |
| score | INTEGER | |
| reason | TEXT | |
| actor | TEXT | `policy_engine` / `user` |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

UNIQUE INDEX ON (job_raw_id, action_type)

#### apply_runs

| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | |
| action_id | INTEGER FK | |
| attempt | INTEGER | |
| status | TEXT | done / failed / already_applied / manual_required / skipped |
| letter_status | TEXT | sent_inline / sent_popup / not_sent / not_needed |
| letter_len | INTEGER | |
| flow_type | TEXT | quick_apply / popup / inline |
| error | TEXT | |
| finished_at | TIMESTAMP | |

#### cover_letters

| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | |
| job_raw_id | INTEGER FK | |
| action_id | INTEGER FK | |
| letter_text | TEXT | |
| is_fallback | BOOLEAN | |
| created_at | TIMESTAMP | |

---

## 3. Pipeline Flows

### 3.1. Scoring Pipeline (обновлённый)

```
Unscored vacancies (TG first, then HH)
    │
    ├── Pre-filter (regex, no LLM) [FR-LLM-02]
    │   └── Reject: стажёр, intern, junior (без PM/Product)
    │       → IGNORE, no LLM call
    │
    ├── Score cache check (by hh_vacancy_id) [FR-LLM-03]
    │   └── If same hh_vacancy_id scored → copy score, no LLM call
    │
    ├── Scoring cap check (safety net, not pipeline limiter)
    │   └── If exceeded → stop scoring for this source
    │       (should rarely happen at cap=500)
    │
    ▼
LLM Scoring (Haiku + prompt caching)
    │
    ▼
Policy → Action → Cover Letter → Notification
```

### 3.2. TG Forward + Link Extraction [FR-SRC-03]

```
User forwards message
    │
    ▼
Extract URLs from message text
    │
    ├── hh.ru/vacancy/XXX → save hh_vacancy_id, fetch via HH API
    ├── Other URLs + keyword match ("описание", "подробнее") → HTTP fetch → extract text
    └── No URLs → use message text as-is
    │
    ▼
Save to job_raw (raw_text = original + extracted description)
    │
    ▼
Reply: "✅ Сохранено: #ID ⏳ Оценка через ~1-2 мин (X/Y)"
```

### 3.3. Apply Pipeline

```
Apply Worker (every 2-5 min)
    │
    ├── Queue: AUTO_APPLY(pending) + APPROVAL_REQUIRED(approved)
    ├── Weekday cap check (Mon=20, Tue-Thu=40, Fri=8, Sat-Sun=0)
    ├── Schedule check (9-20 MSK)
    │
    ├── For each vacancy:
    │   ├── hh_vacancy_id dedup → if applied, mark skipped (NOT counted in cap)
    │   ├── Playwright: open page → check "already applied"
    │   ├── Fill cover letter → submit
    │   ├── Verify submission
    │   └── Count towards apply cap ONLY if actually submitted
    │
    ▼
Notification with title + link + score + cover letter text
```

### 3.4. Approve Flow

```
"✅ Одобрить" callback
    │
    ├── action.status = 'approved'
    ├── Reply: "🚀 Отклик через 30-90 сек..."
    ├── asyncio.create_task(apply THIS vacancy immediately)
    │
    ▼
Apply + Notification (≤ 90 sec total)
```

---

## 4. Configuration

### 4.1. .env

| Variable | Default | Description |
|----------|---------|-------------|
| `HH_SCORING_DAILY_CAP` | 500 | Safety net LLM calls for HH |
| `TG_SCORING_DAILY_CAP` | 50 | Safety net LLM calls for TG |
| `APPLY_DAILY_CAP` | 40 | Main pipeline limiter (×weekday) |
| `HH_APPLY_ENABLED` | true | Master switch |
| `APPLY_SCHEDULE_ENABLED` | true | Enforce 9-20 MSK |
| `APPLY_SCHEDULE_HOUR_START` | 9 | |
| `APPLY_SCHEDULE_HOUR_END` | 20 | |
| `SCORING_THRESHOLD_LOW` | 5 | Below → IGNORE |
| `SCORING_THRESHOLD_HIGH` | 7 | At or above → APPROVAL |

### 4.2. Weekday Multipliers (hardcoded)

Mon=0.5, Tue-Thu=1.0, Fri=0.2, Sat-Sun=0.0

---

## 5. LLM Optimization Stack

| # | Метод | Экономия | Реализация |
|---|-------|----------|------------|
| 1 | **Prompt caching** | ~90% input tokens на резюме | `cache_control: ephemeral` ✅ сделано |
| 2 | **Pre-filter** (regex) | 30-50% LLM-вызовов | keyword blacklist до LLM |
| 3 | **Score cache** (hh_vacancy_id) | ~5-10% LLM-вызовов | SELECT before scoring |
| 4 | **Batch API** (P2) | 50% стоимости | Message Batches API |

---

## 6. Открытые вопросы

| # | Вопрос | Статус |
|---|--------|--------|
| 1 | apply_flow.py 580+ lines → рефактор | Tech debt, P2 |
| 2 | UTC vs MSK в cap reset | Нужно исправить (сброс в 00:00 MSK) |
| 3 | Досылка cover letter в чат HH | P2 |

---

## Changelog

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 13.03.2026 | Первая версия |
| 1.1 | 13.03.2026 | Scoring cap→safety net. Pre-filter, score cache. Link extractor (FR-SRC-03). Apply cap = единственный ограничитель. Skipped ≠ apply cap. |
