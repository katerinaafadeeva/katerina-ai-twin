# PR-5 — Telegram Approval UX + Operator Commands

**Chief Architect Report**
**Date:** 2026-02-23

---

# PART 1: Анализ и решения

## 1.1 Что реализуем

PR-5 замыкает контрольную петлю оператора: сейчас APPROVAL_REQUIRED вакансии отправляются в Telegram как текст, но оператор не может ответить (approve/reject/snooze). PR-5 это исправляет.

Одновременно добавляем operator commands для мониторинга (/today, /stats, /limits).

## 1.2 Чего НЕ делаем в PR-5

- Cover letter generation (требует HH connector, который ещё не готов)
- HH ingestion (PR-6)
- Web UI (Milestone M2)
- Автоматическая отправка откликов (PR-6+)

## 1.3 Ключевые архитектурные решения

### Inline keyboard callback_data format

Формат: `{action}:{action_id}`

Примеры:
- `approve:42` — одобрить action с id=42
- `reject:42` — отклонить
- `snooze:42` — отложить

**Почему action_id, а не job_raw_id:** одна вакансия может иметь несколько actions (rescored, re-evaluated). Action_id — уникальный идентификатор конкретного решения.

### Snooze семантика

Snooze = "не сейчас, напомни позже". Для MVP:
- snooze ставит status='snoozed'
- emit vacancy.snoozed
- **Без таймера.** Snoozed actions появятся в /stats и /today.
- Повторного напоминания в MVP нет (это PR-7+/M2 feature).

**Обоснование:** таймерный snooze требует scheduler (cron/celery). Для 50 вакансий/день и одного оператора — overhead. Если Катерина захочет пересмотреть snoozed вакансии — `/stats` покажет их.

### Migration 005: updated_at

Добавляем `updated_at` в actions. Без этого нельзя отследить КОГДА оператор принял решение. `created_at` = момент создания action policy engine'ом; `updated_at` = момент действия оператора.

### /today vs /stats vs /limits — разграничение

| Команда | Что показывает | Для чего |
|---------|---------------|----------|
| `/today` | Сводка за сегодня: N ingested, N scored, N auto, N approved, N rejected, N snoozed, N pending | Быстрый статус дня |
| `/stats` | То же что /today + % по action_type + pending APPROVAL_REQUIRED list | Детальный обзор |
| `/limits` | Пороги policy (5/7/40), текущий auto count, оставшийся лимит | Проверка ресурсов |

### Где размещать код

Approval handler = часть control_plane skill (не match_scoring). Это operator UX, не scoring logic.

```
capabilities/career_os/skills/control_plane/
├── SKILL.md (update)
├── __init__.py
├── handlers.py     ← callback + commands
└── store.py        ← action state transitions + queries for commands
```

Worker.py модифицируется минимально: APPROVAL_REQUIRED notification теперь включает inline keyboard.

## 1.4 Риски

| Риск | Severity | Mitigation |
|------|----------|-----------|
| Callback timeout (>30s) | MEDIUM | Всегда вызывать answer_callback_query первым; show_alert=False |
| Race condition: два нажатия на кнопку | LOW | Проверять текущий status перед transition; если уже не pending → "Уже обработано" |
| Неавторизованный callback | HIGH | Проверять user_id в callback_query, не только в message |
| action_id не существует | LOW | Graceful error → "Действие не найдено" |
| Кнопки на старых сообщениях | LOW | Проверять status=pending; если нет → "Уже решено" |

---

# PART 2: File Plan

## Migration

| File | Action |
|------|--------|
| `core/migrations/005_actions_updated_at.sql` | CREATE |

## Control Plane skill

| File | Action |
|------|--------|
| `capabilities/career_os/skills/control_plane/__init__.py` | CREATE |
| `capabilities/career_os/skills/control_plane/SKILL.md` | UPDATE |
| `capabilities/career_os/skills/control_plane/handlers.py` | CREATE |
| `capabilities/career_os/skills/control_plane/store.py` | CREATE |

## Worker modification

| File | Action |
|------|--------|
| `capabilities/career_os/skills/match_scoring/worker.py` | MODIFY (APPROVAL_REQUIRED adds keyboard) |

## Telegram bot

| File | Action |
|------|--------|
| `connectors/telegram_bot.py` | MODIFY (register callback + command handlers) |

## Tests

| File | Action |
|------|--------|
| `tests/test_control_plane_store.py` | CREATE |
| `tests/test_control_plane_handlers.py` | CREATE |

## Documentation

| File | Action |
|------|--------|
| `STATUS.md` | UPDATE |
| `CHANGELOG.md` | UPDATE |
| `DECISIONS.md` | UPDATE |
| `BACKLOG.md` | UPDATE |
| `docs/STATUS.md` | UPDATE |

---

# PART 3: Acceptance Criteria

- [ ] APPROVAL_REQUIRED уведомление содержит inline keyboard (Approve / Reject / Snooze)
- [ ] Нажатие Approve: action.status = approved, updated_at записан, event vacancy.approved emitted, ответ "✅ Одобрено"
- [ ] Нажатие Reject: action.status = rejected, updated_at записан, event vacancy.rejected emitted, ответ "❌ Отклонено"
- [ ] Нажатие Snooze: action.status = snoozed, updated_at записан, event vacancy.snoozed emitted, ответ "⏸ Отложено"
- [ ] Повторное нажатие на кнопку → "Уже обработано" (не crash)
- [ ] Неавторизованный user → callback игнорируется
- [ ] /today показывает counts по action_type за сегодня + remaining limit
- [ ] /limits показывает пороги policy + текущий auto count
- [ ] /stats показывает summary + список pending APPROVAL_REQUIRED
- [ ] Все предыдущие 95 тестов зелёные
- [ ] Новые тесты покрывают: state transitions, callback handler logic, commands
- [ ] Policy rules НЕ изменены
