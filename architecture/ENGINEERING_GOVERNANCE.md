# Engineering Governance

## Code Policies

- Python 3.11+
- Type hints обязательны для public functions
- Docstrings обязательны для modules и public functions
- Parameterized SQL only (никогда f-strings)
- No `print()` — использовать `logging`
- UTF-8 everywhere
- Max line length: 100
- Import order: stdlib → third-party → local

## Testing Strategy

| Уровень | Что тестируем | Инструмент |
|---------|--------------|------------|
| Unit | Scoring logic, sanitization, validation | pytest |
| Integration | DB operations, event flow, worker cycle | pytest + in-memory SQLite |
| Fixture-based | Реальные вакансии с known scores | JSON fixtures |
| Security | Prompt injection attempts, PII leakage | Dedicated fixtures |

**Rule:** PR без тестов для бизнес-логики = PR не готов.

## PR Rules

- 1 PR = 1 logical change
- Branch naming: `pr{N}-{short-description}`
- Small commits by subsystem
- Every PR updates: STATUS.md, CHANGELOG.md, DECISIONS.md (if decisions made)

## DoR (Definition of Ready)

- [ ] Цель PR описана (1 предложение)
- [ ] Файлы перечислены
- [ ] Acceptance criteria определены
- [ ] ADR написаны для архитектурных решений
- [ ] Зависимости указаны
- [ ] SKILL.md создан/обновлён

## DoD (Definition of Done)

- [ ] Код соответствует code policies
- [ ] Type hints на public API
- [ ] Тесты написаны и проходят (`pytest`)
- [ ] Security review пройден (QA gate prompt)
- [ ] Нет секретов в коде
- [ ] STATUS.md обновлён
- [ ] CHANGELOG.md обновлён
- [ ] DECISIONS.md обновлён (если решение)
- [ ] Smoke test пройден (manual)

## Event Contract Rules

- Имя: `domain.action` (e.g. `vacancy.scored`, `llm.call`)
- Payload: JSON, обязательные поля задокументированы
- Обязательные мета-поля: `actor`, `correlation_id`
- Append-only: события никогда не удаляются

## Security Review Checklist

- [ ] Input sanitization для untrusted data
- [ ] Нет PII в логах
- [ ] LLM calls аудитированы
- [ ] Auth check на всех endpoints/handlers
- [ ] Secrets только в .env
- [ ] Parameterized SQL
- [ ] Output validation для LLM responses
